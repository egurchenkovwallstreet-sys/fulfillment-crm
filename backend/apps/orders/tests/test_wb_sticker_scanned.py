from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Fulfillment
from apps.orders.models import Order
from apps.orders.services.wb_status import (
  WB_SUPPLIER_DELIVERY,
  apply_wb_status_to_order,
  is_wb_sticker_scanned_status,
  maybe_set_wb_sorted_at,
  order_sticker_scanned_at_wb,
)
from apps.sellers.models import Seller


class WbStickerScannedTests(TestCase):
  def setUp(self):
    self.fulfillment = Fulfillment.objects.create(slug="test-ff", name="Test FF")
    self.seller = Seller.objects.create(
      company_name="Test Seller",
      fulfillment=self.fulfillment,
    )

  def test_is_wb_sticker_scanned_status(self):
    self.assertTrue(
      is_wb_sticker_scanned_status(WB_SUPPLIER_DELIVERY, "sorted"),
    )
    self.assertTrue(
      is_wb_sticker_scanned_status(WB_SUPPLIER_DELIVERY, "ready_for_pickup"),
    )
    self.assertFalse(
      is_wb_sticker_scanned_status(WB_SUPPLIER_DELIVERY, "waiting"),
    )
    self.assertFalse(
      is_wb_sticker_scanned_status(WB_SUPPLIER_DELIVERY, "canceled_by_client"),
    )

  def test_apply_status_sets_wb_sorted_at_for_sorted_order(self):
    order = Order.objects.create(
      seller=self.seller,
      wb_order_id=800001,
      barcode="111",
      status=Order.Status.IN_DELIVERY,
      wb_supplier_status=WB_SUPPLIER_DELIVERY,
      wb_status="waiting",
      in_delivery_at=timezone.now(),
    )
    before = timezone.now()
    apply_wb_status_to_order(order, WB_SUPPLIER_DELIVERY, "sorted")
    order.refresh_from_db()
    self.assertIsNotNone(order.wb_sorted_at)
    self.assertGreaterEqual(order.wb_sorted_at, before)
    self.assertTrue(order_sticker_scanned_at_wb(order))

  def test_apply_status_preserves_sticker_scan_before_buyer_cancel(self):
    order = Order.objects.create(
      seller=self.seller,
      wb_order_id=800002,
      barcode="222",
      status=Order.Status.IN_DELIVERY,
      wb_supplier_status=WB_SUPPLIER_DELIVERY,
      wb_status="sorted",
      in_delivery_at=timezone.now(),
    )
    fixed_at = timezone.now() - timedelta(hours=2)
    order.wb_sorted_at = fixed_at
    order.save(update_fields=["wb_sorted_at", "updated_at"])

    apply_wb_status_to_order(order, WB_SUPPLIER_DELIVERY, "canceled_by_client")
    order.refresh_from_db()
    self.assertEqual(order.wb_sorted_at, fixed_at)
    self.assertTrue(order_sticker_scanned_at_wb(order))

  def test_apply_status_captures_sticker_scan_on_sorted_to_cancel_transition(self):
    order = Order.objects.create(
      seller=self.seller,
      wb_order_id=800003,
      barcode="333",
      status=Order.Status.IN_DELIVERY,
      wb_supplier_status=WB_SUPPLIER_DELIVERY,
      wb_status="sorted",
      in_delivery_at=timezone.now(),
    )
    self.assertIsNone(order.wb_sorted_at)

    apply_wb_status_to_order(order, WB_SUPPLIER_DELIVERY, "canceled_by_client")
    order.refresh_from_db()
    self.assertIsNotNone(order.wb_sorted_at)
    self.assertTrue(order_sticker_scanned_at_wb(order))

  def test_maybe_set_wb_sorted_at_uses_explicit_timestamp(self):
    order = Order.objects.create(
      seller=self.seller,
      wb_order_id=800004,
      barcode="444",
      status=Order.Status.SHIPPED,
      wb_supplier_status=WB_SUPPLIER_DELIVERY,
      wb_status="sold",
    )
    fixed_at = timezone.now() - timedelta(days=1)
    self.assertTrue(
      maybe_set_wb_sorted_at(
        order,
        WB_SUPPLIER_DELIVERY,
        "sold",
        at=fixed_at,
      ),
    )
    self.assertEqual(order.wb_sorted_at, fixed_at)
