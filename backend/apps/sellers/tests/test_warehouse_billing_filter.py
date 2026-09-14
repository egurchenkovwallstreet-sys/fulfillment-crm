from decimal import Decimal

from django.test import TestCase

from apps.accounts.models import Fulfillment
from apps.integrations.marketplace import WB
from apps.orders.models import Order, Supply
from apps.sellers.models import ExcludedSellerWarehouse, Seller, SellerWarehouse, ShipmentUnitCharge
from apps.sellers.services.seller_billing_stats import (
  _ShippedOrderMeta,
  _order_eligible_for_billing,
  _sum_shipped_orders,
)
from apps.sellers.services.warehouse_filter import get_billing_warehouse_match_ids
from apps.warehouse.models import Cell, Product


class WarehouseBillingFilterTests(TestCase):
  def setUp(self):
    self.fulfillment = Fulfillment.objects.create(slug="billing-ff", name="Billing FF")
    self.seller = Seller.objects.create(
      company_name="Billing Seller",
      fulfillment=self.fulfillment,
    )
    self.cell = Cell.objects.create(seller=self.seller, number="1", marketplace=WB)
    self.product = Product.objects.create(
      seller=self.seller,
      cell=self.cell,
      barcode="4600000000001",
      marketplace=WB,
      individual_price=Decimal("10.00"),
      quantity=5,
    )

  def test_billing_match_ids_include_disabled_warehouse(self):
    SellerWarehouse.objects.create(
      seller=self.seller,
      wb_warehouse_id=501,
      name="Disabled WH",
      is_enabled=False,
    )
    match_ids = get_billing_warehouse_match_ids(self.seller)
    self.assertIn(501, match_ids)

  def test_billing_match_ids_include_deleted_warehouse(self):
    ExcludedSellerWarehouse.objects.create(
      seller=self.seller,
      marketplace=WB,
      warehouse_external_id=777,
      name="Deleted WH",
    )
    match_ids = get_billing_warehouse_match_ids(self.seller)
    self.assertIn(777, match_ids)

  def test_billing_match_ids_include_order_history(self):
    Order.objects.create(
      seller=self.seller,
      wb_order_id=9001,
      barcode=self.product.barcode,
      wb_warehouse_id=888,
      product=self.product,
    )
    match_ids = get_billing_warehouse_match_ids(self.seller)
    self.assertIn(888, match_ids)

  def test_order_eligible_after_warehouse_disabled(self):
    SellerWarehouse.objects.create(
      seller=self.seller,
      wb_warehouse_id=601,
      is_enabled=False,
    )
    meta = _ShippedOrderMeta(barcode=self.product.barcode, warehouse_id=601)
    self.assertTrue(
      _order_eligible_for_billing(
        self.seller,
        meta,
        match_ids=get_billing_warehouse_match_ids(self.seller),
        wb_order_id=12345,
      )
    )

  def test_sum_shipped_orders_keeps_deleted_warehouse_history(self):
    ExcludedSellerWarehouse.objects.create(
      seller=self.seller,
      marketplace=WB,
      warehouse_external_id=909,
      name="Old WH",
    )
    ShipmentUnitCharge.objects.create(
      seller=self.seller,
      product=self.product,
      barcode=self.product.barcode,
      marketplace=WB,
      wb_order_id=555001,
      charge_date="2026-09-01",
      quantity=1,
      unit_price=Decimal("10.00"),
      amount=Decimal("10.00"),
    )
    order_index = {
      555001: _ShippedOrderMeta(
        barcode=self.product.barcode,
        warehouse_id=909,
      ),
    }
    count, amount = _sum_shipped_orders(
      self.seller,
      [555001],
      order_index=order_index,
      price_by_barcode={self.product.barcode: Decimal("10.00")},
      fallback_tariff=Decimal("10.00"),
      match_ids=get_billing_warehouse_match_ids(self.seller),
    )
    self.assertEqual(count, 1)
    self.assertEqual(amount, Decimal("10.00"))

  def test_supply_warehouse_in_billing_match_ids(self):
    Supply.objects.create(
      seller=self.seller,
      wb_supply_id="WB-SUP-1",
      wb_warehouse_id=4321,
      status=Supply.Status.CONFIRMED,
    )
    match_ids = get_billing_warehouse_match_ids(self.seller)
    self.assertIn(4321, match_ids)
