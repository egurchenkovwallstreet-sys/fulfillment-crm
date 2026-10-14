from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Fulfillment
from apps.integrations.marketplace import WB
from apps.orders.models import Order
from apps.sellers.models import Seller, SellerWarehouse, ShipmentUnitCharge
from apps.sellers.services.delivery_billing import load_weekly_shipped_orders
from apps.warehouse.models import Product, StockOperation


class DeliveryBillingStatsTests(TestCase):
  def setUp(self):
    self.fulfillment = Fulfillment.objects.create(slug="test-ff", name="Test FF")
    self.seller = Seller.objects.create(
      company_name="Delivery Seller",
      fulfillment=self.fulfillment,
      wb_enabled=True,
    )
    SellerWarehouse.objects.create(
      seller=self.seller,
      wb_warehouse_id=100,
      name="Main WH",
      is_enabled=True,
    )
    self.product = Product.objects.create(
      seller=self.seller,
      barcode="4609999999999",
      name="Test",
      quantity=10,
      individual_price=Decimal("35.00"),
    )
    self.order = Order.objects.create(
      seller=self.seller,
      wb_order_id=800001,
      barcode=self.product.barcode,
      product=self.product,
      wb_warehouse_id=100,
      status=Order.Status.IN_DELIVERY,
      in_delivery_at=timezone.now(),
    )

  def test_weekly_stats_count_delivery_not_sticker_prefetch(self):
    self.order.has_sticker = True
    self.order.sticker_fetched_at = timezone.now()
    self.order.in_delivery_at = None
    self.order.status = Order.Status.IN_PICKING
    self.order.save(
      update_fields=["has_sticker", "sticker_fetched_at", "in_delivery_at", "status", "updated_at"],
    )
    payload = load_weekly_shipped_orders(self.seller)
    current = payload["weeks"][0]
    self.assertEqual(current["total"], 0)

  def test_weekly_stats_count_in_delivery(self):
    payload = load_weekly_shipped_orders(self.seller)
    current = payload["weeks"][0]
    self.assertEqual(current["total"], 1)
    self.assertGreaterEqual(Decimal(str(current["total_amount"])), Decimal("35"))

  def test_stale_sticker_charge_without_delivery_not_counted(self):
    charge_date = timezone.localtime(timezone.now()).date()
    self.order.in_delivery_at = None
    self.order.save(update_fields=["in_delivery_at", "updated_at"])
    ShipmentUnitCharge.objects.create(
      seller=self.seller,
      barcode=self.product.barcode,
      marketplace=WB,
      order=self.order,
      wb_order_id=self.order.wb_order_id,
      charge_date=charge_date,
      quantity=1,
      unit_price=Decimal("35.00"),
      amount=Decimal("35.00"),
    )

    payload = load_weekly_shipped_orders(self.seller)
    current = payload["weeks"][0]
    self.assertEqual(current["total"], 0)

  def test_disabled_warehouse_not_counted(self):
    self.order.wb_warehouse_id = 999
    self.order.save(update_fields=["wb_warehouse_id", "updated_at"])
    payload = load_weekly_shipped_orders(self.seller)
    current = payload["weeks"][0]
    self.assertEqual(current["total"], 0)

  def test_sticker_stock_op_without_delivery_not_counted(self):
    StockOperation.objects.create(
      product=self.product,
      operation_type=StockOperation.OperationType.SHIPMENT,
      quantity=-1,
      comment=(
        f"Списание: стикер FBS A1|B1, баркод {self.product.barcode}, "
        f"заказ #{self.order.wb_order_id}"
      ),
    )
    self.order.in_delivery_at = None
    self.order.status = Order.Status.LABEL_PRINTED
    self.order.save(update_fields=["in_delivery_at", "status", "updated_at"])
    payload = load_weekly_shipped_orders(self.seller)
    current = payload["weeks"][0]
    self.assertEqual(current["total"], 0)
