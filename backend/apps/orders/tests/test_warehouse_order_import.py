from django.test import TestCase

from apps.accounts.models import Fulfillment
from apps.integrations.wb_client import WBOrderData
from apps.orders.models import Order
from apps.orders.services.sync_orders import _import_wb_orders, _repair_orders_warehouse_ids
from apps.orders.services.wb_status import WB_SUPPLIER_NEW
from apps.sellers.models import Seller, SellerWarehouse
from apps.sellers.services.warehouse_filter import (
  is_warehouse_enabled,
  resolve_wb_order_warehouse_id,
)


class WarehouseOrderImportTests(TestCase):
  def setUp(self):
    self.fulfillment = Fulfillment.objects.create(slug="wh-import", name="WH Import FF")
    self.seller = Seller.objects.create(
      company_name="WH Import Seller",
      fulfillment=self.fulfillment,
      wb_enabled=True,
    )
    SellerWarehouse.objects.create(
      seller=self.seller,
      wb_warehouse_id=501,
      office_id=8801,
      name="Domodedovo",
      is_enabled=True,
    )

  def test_office_id_matches_enabled_warehouse(self):
    self.assertTrue(is_warehouse_enabled(self.seller, None, 8801))
    self.assertFalse(is_warehouse_enabled(self.seller, None, 9999))
    self.assertEqual(resolve_wb_order_warehouse_id(self.seller, None, 8801), 501)

  def test_import_new_order_by_office_id(self):
    wb_order = WBOrderData(
      wb_order_id=700001,
      barcode="4609999999999",
      warehouse_id=None,
      office_id=8801,
    )
    result = _import_wb_orders(self.seller, [wb_order], mark_as_new=True)
    self.assertEqual(result["skipped_warehouse"], 0)
    order = Order.objects.get(wb_order_id=700001)
    self.assertEqual(order.wb_warehouse_id, 501)
    self.assertEqual(order.wb_supplier_status, WB_SUPPLIER_NEW)

  def test_repair_existing_order_with_wrong_warehouse(self):
    Order.objects.create(
      seller=self.seller,
      wb_order_id=700002,
      barcode="4608888888888",
      wb_warehouse_id=8801,
      status=Order.Status.NEW,
      wb_supplier_status=WB_SUPPLIER_NEW,
    )
    wb_order = WBOrderData(
      wb_order_id=700002,
      barcode="4608888888888",
      warehouse_id=None,
      office_id=8801,
    )
    fixed = _repair_orders_warehouse_ids(self.seller, [wb_order])
    self.assertEqual(fixed, 1)
    order = Order.objects.get(wb_order_id=700002)
    self.assertEqual(order.wb_warehouse_id, 501)
