from datetime import date

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Fulfillment
from apps.integrations.marketplace import WB
from apps.orders.models import OffCrmShipment, Order, Supply
from apps.sellers.models import Seller, SellerWarehouse
from apps.sellers.services.supply_report import load_supply_report, parse_report_month


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
      status=Supply.Status.CONFIRMED,
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
      wb_status="waiting",
    )
    self.supply.orders.add(self.crm_order)
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

  def test_load_supply_report_includes_crm_and_off_crm(self):
    month = timezone.localdate().replace(day=1)
    payload = load_supply_report(self.fulfillment, month=month)
    self.assertEqual(payload["totals"]["supplies"], 1)
    row = payload["supplies"][0]
    self.assertEqual(row["wb_supply_id"], "WB-SUP-REPORT")
    self.assertEqual(row["crm_orders_count"], 1)
    self.assertEqual(row["off_crm_orders_count"], 1)
    self.assertIn("/", row["shipment_dates"])
    self.assertEqual(row["crm_orders"][0]["wb_order_id"], 700001)
    self.assertEqual(row["off_crm_orders"][0]["wb_order_id"], 700002)
