from unittest.mock import MagicMock

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Fulfillment
from apps.orders.models import Order, Supply
from apps.orders.services.supply_flow import delivery_stage_orders_queryset
from apps.orders.services.supply_sync import _sync_crm_orders_delivery_status
from apps.orders.services.sync_statuses import reconcile_stale_delivery_orders
from apps.orders.services.wb_status import WB_STATUS_AFTER_DELIVER, WB_SUPPLIER_DELIVERY
from apps.sellers.models import Seller


class IndividualDeliveryAcceptanceTests(TestCase):
  def setUp(self):
    self.fulfillment = Fulfillment.objects.create(slug="test-ff", name="Test FF")
    self.seller = Seller.objects.create(
      company_name="Test Seller",
      fulfillment=self.fulfillment,
      wb_enabled=True,
      wb_api_token_encrypted="enc",
    )
    self.supply = Supply.objects.create(
      seller=self.seller,
      wb_supply_id="WB-SUP-MIX",
      status=Supply.Status.CONFIRMED,
    )
    self.accepted = Order.objects.create(
      seller=self.seller,
      wb_order_id=900101,
      barcode="4601111111111",
      status=Order.Status.IN_DELIVERY,
      wb_supplier_status=WB_SUPPLIER_DELIVERY,
      wb_status="sorted",
      in_delivery_at=timezone.now(),
    )
    self.waiting = Order.objects.create(
      seller=self.seller,
      wb_order_id=900102,
      barcode="4602222222222",
      status=Order.Status.IN_DELIVERY,
      wb_supplier_status=WB_SUPPLIER_DELIVERY,
      wb_status=WB_STATUS_AFTER_DELIVER,
      in_delivery_at=timezone.now(),
    )
    self.supply.orders.add(self.accepted, self.waiting)

  def test_supply_sync_without_scan_dt_does_not_revert_sorted_order(self):
    _sync_crm_orders_delivery_status(
      [self.accepted, self.waiting],
      seller=self.seller,
      scanned_at=None,
    )

    self.accepted.refresh_from_db()
    self.waiting.refresh_from_db()
    self.assertEqual(self.accepted.status, Order.Status.SHIPPED)
    self.assertEqual(self.accepted.wb_status, "sorted")
    self.assertEqual(self.waiting.status, Order.Status.IN_DELIVERY)
    self.assertEqual(self.waiting.wb_status, WB_STATUS_AFTER_DELIVER)

  def test_delivery_tab_hides_individually_accepted_order(self):
    visible_ids = set(delivery_stage_orders_queryset(self.seller).values_list("id", flat=True))
    self.assertNotIn(self.accepted.id, visible_ids)
    self.assertIn(self.waiting.id, visible_ids)

  def test_reconcile_stale_delivery_closes_sorted_order_from_wb(self):
    client = MagicMock()
    status_map = {
      self.waiting.wb_order_id: {
        "id": self.waiting.wb_order_id,
        "supplierStatus": WB_SUPPLIER_DELIVERY,
        "wbStatus": "sorted",
      },
    }

    result = reconcile_stale_delivery_orders(self.seller, client, status_map)

    self.waiting.refresh_from_db()
    self.assertEqual(result["stale_delivery_cleared"], 1)
    self.assertEqual(self.waiting.status, Order.Status.SHIPPED)
    self.assertEqual(self.waiting.wb_status, "sorted")
