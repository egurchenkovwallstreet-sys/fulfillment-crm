from datetime import datetime, timedelta

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Fulfillment
from apps.integrations.marketplace import OZON, WB
from apps.integrations.models import AuditLog
from apps.orders.models import Order
from apps.sellers.models import Seller
from apps.sellers.services.crm_product_stats import (
  PERIOD_ALL,
  PERIOD_DAY,
  STATS_SOURCE,
  load_crm_product_shipment_stats,
  resolve_stats_period,
)
from apps.warehouse.models import Cell, Product, StockOperation


class CrmProductStatsTests(TestCase):
  def setUp(self):
    self.fulfillment = Fulfillment.objects.create(slug="test-ff", name="Test FF")
    self.seller = Seller.objects.create(
      company_name="Test Seller",
      fulfillment=self.fulfillment,
    )
    self.wb_cell = Cell.objects.create(seller=self.seller, number="WB-1", marketplace=WB)
    self.ozon_cell = Cell.objects.create(seller=self.seller, number="OZ-1", marketplace=OZON)
    self.today = timezone.localdate()
    self.yesterday = self.today - timedelta(days=1)

  def _wb_product(self, barcode: str) -> Product:
    return Product.objects.create(
      seller=self.seller,
      cell=self.wb_cell,
      barcode=barcode,
      marketplace=WB,
      quantity=10,
    )

  def _ozon_product(self, barcode: str) -> Product:
    return Product.objects.create(
      seller=self.seller,
      cell=self.ozon_cell,
      barcode=barcode,
      marketplace=OZON,
      quantity=10,
    )

  def _sticker_deduction(self, product: Product, *, wb_order_id: int, at=None):
    op = StockOperation.objects.create(
      product=product,
      operation_type=StockOperation.OperationType.SHIPMENT,
      quantity=1,
      comment=(
        f"Списание: стикер FBS A|B, баркод {product.barcode}, "
        f"заказ #{wb_order_id}"
      ),
    )
    if at is not None:
      StockOperation.objects.filter(pk=op.pk).update(created_at=at)
    return op

  def test_wb_counts_sticker_stock_deduction(self):
    product = self._wb_product("222")
    self._sticker_deduction(product, wb_order_id=1003)

    Order.objects.create(
      seller=self.seller,
      wb_order_id=1002,
      barcode="111",
      status=Order.Status.SHIPPED,
      in_delivery_at=timezone.now(),
    )
    AuditLog.objects.create(
      seller=self.seller,
      action_type=AuditLog.ActionType.SUPPLY,
      message="В доставку (WB): заказ #1002, поставка WB-1",
      details={"order_id": 1, "wb_supply_id": "WB-1"},
    )

    payload = load_crm_product_shipment_stats(self.seller, period=PERIOD_ALL)
    self.assertEqual(payload["source"], STATS_SOURCE)
    self.assertEqual(payload["total_units"], 1)
    self.assertEqual(payload["items"][0]["barcode"], "222")

  def test_wb_ignores_legacy_supply_deduction(self):
    product = self._wb_product("111")
    StockOperation.objects.create(
      product=product,
      operation_type=StockOperation.OperationType.SHIPMENT,
      quantity=1,
      comment="Списание: поставка WB WB-1, заказ #1001",
    )

    payload = load_crm_product_shipment_stats(self.seller, period=PERIOD_ALL)
    self.assertEqual(payload["total_units"], 0)

  def test_period_day_filters_by_stock_operation_date(self):
    product = self._wb_product("111")
    self._sticker_deduction(
      product,
      wb_order_id=1004,
      at=timezone.make_aware(datetime.combine(self.today, datetime.min.time())),
    )
    self._sticker_deduction(
      product,
      wb_order_id=1005,
      at=timezone.make_aware(datetime.combine(self.yesterday, datetime.min.time())),
    )

    payload = load_crm_product_shipment_stats(self.seller, period=PERIOD_DAY)
    self.assertEqual(payload["total_units"], 1)

  def test_ozon_counts_stock_deduction_quantity(self):
    product = self._ozon_product("OZ-111")
    StockOperation.objects.create(
      product=product,
      operation_type=StockOperation.OperationType.SHIPMENT,
      quantity=-3,
      comment="Ozon OZ-1",
    )

    payload = load_crm_product_shipment_stats(self.seller, marketplace="ozon", period=PERIOD_ALL)
    self.assertEqual(payload["source"], STATS_SOURCE)
    self.assertEqual(payload["total_units"], 3)

  def test_barcode_search(self):
    product = self._wb_product("4601234567890")
    other = self._wb_product("999")
    self._sticker_deduction(product, wb_order_id=1006)
    self._sticker_deduction(other, wb_order_id=1007)

    payload = load_crm_product_shipment_stats(
      self.seller,
      period=PERIOD_ALL,
      barcode="460123",
    )
    self.assertEqual(payload["total_units"], 1)
    self.assertEqual(payload["items"][0]["barcode"], "4601234567890")

  def test_resolve_custom_period_swaps_dates(self):
    start, end, preset = resolve_stats_period(
      period="custom",
      date_from=self.today,
      date_to=self.yesterday,
    )
    self.assertEqual(preset, "custom")
    self.assertEqual(start, self.yesterday)
    self.assertEqual(end, self.today)
