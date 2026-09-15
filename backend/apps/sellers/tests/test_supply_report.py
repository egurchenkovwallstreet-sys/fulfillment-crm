from datetime import date

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Fulfillment
from apps.integrations.marketplace import WB
from apps.orders.models import OffCrmShipment, Order, Supply
from apps.sellers.models import Seller, SellerWarehouse
from apps.sellers.services.supply_report import (
  describe_order_cancellation,
  load_supply_report,
  parse_report_month,
  wb_sc_acceptance_label,
)


class SupplyReportTests(TestCase):
  def setUp(self):
    self.fulfillment = Fulfillment.objects.create(slug="test-ff", name="Test FF")
    self.seller = Seller.objects.create(
      company_name="Test Seller",
      fulfillment=self.fulfillment,
    )
    SellerWarehouse.objects.create(
      seller=self.seller,
      wb_warehouse_id=1001,
      name="Склад А",
      is_enabled=True,
    )
    self.supply = Supply.objects.create(
      seller=self.seller,
      wb_supply_id="WB-SUP-REPORT",
      wb_warehouse_id=1001,
      status=Supply.Status.READY,
      wb_scanned_at=timezone.now(),
    )
    self.crm_order = Order.objects.create(
      seller=self.seller,
      wb_order_id=700001,
      barcode="111",
      status=Order.Status.IN_DELIVERY,
      has_sticker=True,
      in_delivery_at=timezone.now(),
      wb_warehouse_id=1001,
      wb_supplier_status="complete",
      wb_status="sorted",
    )
    self.buyer_cancel_order = Order.objects.create(
      seller=self.seller,
      wb_order_id=700003,
      barcode="333",
      status=Order.Status.CANCELLED,
      has_sticker=True,
      in_delivery_at=timezone.now(),
      wb_warehouse_id=1001,
      wb_supplier_status="complete",
      wb_status="canceled_by_client",
    )
    self.seller_cancel_order = Order.objects.create(
      seller=self.seller,
      wb_order_id=700004,
      barcode="444",
      status=Order.Status.CANCELLED,
      has_sticker=True,
      wb_warehouse_id=1001,
      wb_supplier_status="cancel",
      wb_status="canceled",
    )
    self.supply.orders.add(self.crm_order, self.buyer_cancel_order, self.seller_cancel_order)
    OffCrmShipment.objects.create(
      seller=self.seller,
      wb_order_id=700002,
      barcode="222",
      sticker_part_a="A2",
      sticker_part_b="B2",
      wb_supply_id="WB-SUP-REPORT",
      wb_warehouse_id=1001,
      warehouse_name="Склад А",
      shipped_at=timezone.now(),
      status=OffCrmShipment.Status.PENDING,
    )

  def test_parse_report_month(self):
    self.assertEqual(parse_report_month("2026-09"), date(2026, 9, 1))
    self.assertIsNone(parse_report_month("bad"))

  def test_wb_sc_acceptance_label(self):
    self.assertEqual(wb_sc_acceptance_label(self.crm_order), "Отсортирован")

  def test_seller_cancel_where(self):
    cancel = describe_order_cancellation(self.seller_cancel_order, self.supply)
    self.assertEqual(cancel["cancel_party"], "seller")
    self.assertIn("поставке", cancel["cancel_where_label"])

  def test_buyer_cancel(self):
    cancel = describe_order_cancellation(self.buyer_cancel_order, self.supply)
    self.assertEqual(cancel["cancel_party"], "buyer")
    self.assertEqual(cancel["cancel_detail_label"], "Отменён покупателем")

  def test_load_supply_report_includes_all_orders(self):
    month = timezone.localdate().replace(day=1)
    payload = load_supply_report(self.fulfillment, month=month)
    self.assertEqual(payload["totals"]["supplies"], 1)
    row = payload["supplies"][0]
    self.assertEqual(row["crm_orders_count"], 3)
    self.assertEqual(row["off_crm_orders_count"], 1)
    crm_ids = {item["wb_order_id"] for item in row["crm_orders"]}
    self.assertEqual(crm_ids, {700001, 700003, 700004})

  def test_buyer_cancel_without_sorting(self):
    from apps.sellers.services.supply_report import wb_sc_acceptance_label

    self.assertEqual(
      wb_sc_acceptance_label(self.buyer_cancel_order, self.supply),
      "Передан в доставку · не отсортирован",
    )

  def test_buyer_cancel_with_sorting_date(self):
    from apps.sellers.services.supply_report import wb_sc_acceptance_label

    self.buyer_cancel_order.wb_sorted_at = timezone.now()
    self.buyer_cancel_order.save(update_fields=["wb_sorted_at", "updated_at"])
    self.assertEqual(
      wb_sc_acceptance_label(self.buyer_cancel_order, self.supply),
      "Был отгружен на СЦ WB",
    )

  def test_sticker_search_filters_orders(self):
    self.crm_order.sticker_part_a = "12345"
    self.crm_order.sticker_part_b = "67890"
    self.crm_order.save(update_fields=["sticker_part_a", "sticker_part_b", "updated_at"])
    month = timezone.localdate().replace(day=1)
    payload = load_supply_report(self.fulfillment, month=month, sticker_query="12345")
    self.assertEqual(payload["totals"]["crm_orders"], 1)
    self.assertEqual(payload["supplies"][0]["crm_orders"][0]["wb_order_id"], 700001)
