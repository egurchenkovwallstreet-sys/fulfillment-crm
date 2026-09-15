from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Fulfillment
from apps.integrations.marketplace import WB
from apps.orders.models import Order
from apps.sellers.models import ExcludedSellerWarehouse, Seller, ShipmentUnitCharge
from apps.sellers.services.sticker_billing import load_weekly_shipped_orders
from apps.warehouse.models import Product, StockOperation


class StickerBillingStatsTests(TestCase):
  def setUp(self):
    self.fulfillment = Fulfillment.objects.create(slug="test-ff", name="Test FF")
    self.seller = Seller.objects.create(
      company_name="Sticker Seller",
      fulfillment=self.fulfillment,
      wb_enabled=True,
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
      status=Order.Status.LABEL_PRINTED,
      sticker_part_a="A1",
      sticker_part_b="B1",
    )

  def _record_sticker_print(self):
    StockOperation.objects.create(
      product=self.product,
      operation_type=StockOperation.OperationType.SHIPMENT,
      quantity=-1,
      comment=(
        f"Списание: стикер FBS A1|B1, баркод {self.product.barcode}, "
        f"заказ #{self.order.wb_order_id}"
      ),
    )

  def test_weekly_stats_count_only_sticker_prints(self):
    self._record_sticker_print()
    payload = load_weekly_shipped_orders(self.seller)
    current = payload["weeks"][0]
    self.assertEqual(current["total"], 1)
    self.assertGreaterEqual(Decimal(str(current["total_amount"])), Decimal("35"))

  def test_orders_without_sticker_print_not_counted(self):
    payload = load_weekly_shipped_orders(self.seller)
    current = payload["weeks"][0]
    self.assertEqual(current["total"], 0)

  def test_billing_counts_shipment_unit_charge_without_stock_operation(self):
    charge_date = timezone.localtime(timezone.now()).date()
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
    StockOperation.objects.filter(product=self.product).delete()
    self.product.delete()

    payload = load_weekly_shipped_orders(self.seller)
    current = payload["weeks"][0]
    self.assertEqual(current["total"], 1)
    self.assertEqual(Decimal(str(current["total_amount"])), Decimal("35.00"))

  def test_billing_counts_order_with_sticker_when_product_removed(self):
    self.order.has_sticker = True
    self.order.sticker_fetched_at = timezone.now()
    self.order.save(update_fields=["has_sticker", "sticker_fetched_at", "updated_at"])
    StockOperation.objects.filter(product=self.product).delete()
    self.product.delete()

    payload = load_weekly_shipped_orders(self.seller)
    current = payload["weeks"][0]
    self.assertEqual(current["total"], 1)

  def test_billing_keeps_deleted_warehouse_history(self):
    charge_date = timezone.localtime(timezone.now()).date()
    ExcludedSellerWarehouse.objects.create(
      seller=self.seller,
      marketplace=WB,
      warehouse_external_id=909,
      name="Deleted WH",
    )
    self.order.wb_warehouse_id = 909
    self.order.has_sticker = True
    self.order.sticker_fetched_at = timezone.now()
    self.order.save(
      update_fields=["wb_warehouse_id", "has_sticker", "sticker_fetched_at", "updated_at"],
    )
    ShipmentUnitCharge.objects.create(
      seller=self.seller,
      barcode=self.order.barcode,
      marketplace=WB,
      order=self.order,
      wb_order_id=self.order.wb_order_id,
      charge_date=charge_date,
      quantity=1,
      unit_price=Decimal("35.00"),
      amount=Decimal("35.00"),
    )
    self.product.delete()

    payload = load_weekly_shipped_orders(self.seller)
    current = payload["weeks"][0]
    self.assertEqual(current["total"], 1)
    self.assertEqual(Decimal(str(current["total_amount"])), Decimal("35.00"))
