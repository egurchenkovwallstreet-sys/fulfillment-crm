from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Fulfillment
from apps.orders.models import Order
from apps.orders.services.assembly import get_seller_wb_tab_counts
from apps.orders.services.supply_flow import get_assembly_stage_counts
from apps.orders.services.wb_status import (
  WB_STATUS_AFTER_DELIVER,
  WB_SUPPLIER_ASSEMBLY,
  WB_SUPPLIER_DELIVERY,
  WB_SUPPLIER_NEW,
  get_wb_lk_tab_counts,
)
from apps.sellers.models import Seller, SellerWarehouse


class WbLkTabCountsTests(TestCase):
  def setUp(self):
    self.fulfillment = Fulfillment.objects.create(slug="wb-lk-ff", name="WB LK FF")
    self.seller = Seller.objects.create(
      company_name="WB LK Seller",
      fulfillment=self.fulfillment,
      wb_enabled=True,
      wb_api_token_encrypted="token",
      wb_new_order_ids=[1001, 1002],
      wb_counts_synced_at=timezone.now(),
    )
    SellerWarehouse.objects.create(
      seller=self.seller,
      wb_warehouse_id=501,
      name="Enabled WH",
      is_enabled=True,
    )
    SellerWarehouse.objects.create(
      seller=self.seller,
      wb_warehouse_id=999,
      name="Disabled WH",
      is_enabled=False,
    )

  def _create_order(self, **kwargs):
    defaults = {
      "seller": self.seller,
      "barcode": "4600000000001",
      "assembly_hidden": False,
    }
    defaults.update(kwargs)
    return Order.objects.create(**defaults)

  def test_only_enabled_warehouse_orders_counted(self):
    self._create_order(
      wb_order_id=1001,
      wb_warehouse_id=501,
      wb_supplier_status=WB_SUPPLIER_NEW,
      status=Order.Status.NEW,
    )
    self._create_order(
      wb_order_id=1002,
      wb_warehouse_id=999,
      wb_supplier_status=WB_SUPPLIER_NEW,
      status=Order.Status.NEW,
    )
    self._create_order(
      wb_order_id=2001,
      wb_warehouse_id=501,
      wb_supplier_status=WB_SUPPLIER_ASSEMBLY,
      status=Order.Status.IN_PICKING,
    )
    self._create_order(
      wb_order_id=3001,
      wb_warehouse_id=501,
      wb_supplier_status=WB_SUPPLIER_DELIVERY,
      wb_status=WB_STATUS_AFTER_DELIVER,
      status=Order.Status.IN_DELIVERY,
    )

    counts = get_wb_lk_tab_counts(self.seller)
    self.assertEqual(counts["new"], 1)
    self.assertEqual(counts["in_picking"], 1)
    self.assertEqual(counts["in_delivery"], 1)

  def test_all_count_sources_match(self):
    self._create_order(
      wb_order_id=1001,
      wb_warehouse_id=501,
      wb_supplier_status=WB_SUPPLIER_NEW,
      status=Order.Status.NEW,
    )
    self._create_order(
      wb_order_id=2001,
      wb_warehouse_id=501,
      wb_supplier_status=WB_SUPPLIER_ASSEMBLY,
      status=Order.Status.IN_PICKING,
    )

    lk = get_wb_lk_tab_counts(self.seller)
    tab = get_seller_wb_tab_counts(self.seller, assembly_only=True)
    assembly = get_assembly_stage_counts(self.seller)
    self.assertEqual(lk, tab)
    self.assertEqual(lk, assembly)

  def test_sorted_order_not_in_delivery_count(self):
    self._create_order(
      wb_order_id=3001,
      wb_warehouse_id=501,
      wb_supplier_status=WB_SUPPLIER_DELIVERY,
      wb_status="sorted",
      status=Order.Status.SHIPPED,
    )
    self._create_order(
      wb_order_id=3002,
      wb_warehouse_id=501,
      wb_supplier_status=WB_SUPPLIER_DELIVERY,
      wb_status=WB_STATUS_AFTER_DELIVER,
      status=Order.Status.IN_DELIVERY,
    )

    counts = get_wb_lk_tab_counts(self.seller)
    self.assertEqual(counts["in_delivery"], 1)

  def test_hidden_orders_excluded(self):
    self._create_order(
      wb_order_id=1001,
      wb_warehouse_id=501,
      wb_supplier_status=WB_SUPPLIER_NEW,
      status=Order.Status.NEW,
      assembly_hidden=True,
    )

    counts = get_wb_lk_tab_counts(self.seller)
    self.assertEqual(counts["new"], 0)
