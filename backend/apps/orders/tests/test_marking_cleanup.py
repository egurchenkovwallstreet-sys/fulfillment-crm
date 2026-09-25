from django.test import TestCase

from apps.accounts.models import Fulfillment, User
from apps.orders.models import Order
from apps.orders.services.marking_cleanup import (
  _order_has_marking_data,
  clear_daily_shipped_marking_codes,
)
from apps.sellers.models import Seller
from apps.warehouse.models import Cell, Product


class MarkingCleanupDailyTest(TestCase):
  def setUp(self):
    self.fulfillment = Fulfillment.objects.create(slug="ff-cln", name="FF")
    self.seller = Seller.objects.create(
      company_name="Cleanup",
      fulfillment=self.fulfillment,
      wb_enabled=True,
    )
    self.cell = Cell.objects.create(seller=self.seller, number="A1", marketplace="wb")
    self.product = Product.objects.create(
      seller=self.seller,
      barcode="4600000000001",
      cell=self.cell,
      requires_marking=True,
    )

  def test_daily_clears_marking_on_assembly_order_not_only_shipped(self):
    order = Order.objects.create(
      seller=self.seller,
      wb_order_id=700001,
      barcode="4600000000001",
      product=self.product,
      status=Order.Status.ASSEMBLED,
      wb_supplier_status="confirm",
      marking_code="0104600000000010215ABC1234567890",
      marking_verify_status="pending",
    )
    result = clear_daily_shipped_marking_codes()
    order.refresh_from_db()

    self.assertGreaterEqual(result["wb_cleared"], 1)
    self.assertEqual(result["mode"], "daily_all_crm")
    self.assertFalse(_order_has_marking_data(order))

  def test_daily_clears_shipped_order_marking(self):
    order = Order.objects.create(
      seller=self.seller,
      wb_order_id=700002,
      barcode="4600000000001",
      product=self.product,
      status=Order.Status.SHIPPED,
      marking_code="0104600000000010215XYZ9876543210",
      marking_bound=True,
    )
    clear_daily_shipped_marking_codes()
    order.refresh_from_db()
    self.assertFalse(_order_has_marking_data(order))
