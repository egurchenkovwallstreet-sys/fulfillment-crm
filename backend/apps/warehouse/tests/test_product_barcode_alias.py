from django.test import TestCase

from apps.accounts.models import Fulfillment
from apps.integrations.marketplace import WB
from apps.orders.models import Order, PickList, PickListItem
from apps.orders.services.assembly import (
  _match_order_by_scan,
  _scan_allowed_in_pick_list,
  scan_order_barcode,
)
from apps.orders.services.pick_list import _products_by_barcode
from apps.sellers.models import Seller
from apps.warehouse.models import Cell, Product, ProductBarcodeAlias
from apps.warehouse.services.catalog_fetch import CatalogBarcodeItem
from apps.warehouse.services.product_lookup import (
  build_wb_chrt_product_map,
  relink_orders_to_products_for_seller,
  resolve_product_by_barcode,
)


class ProductBarcodeAliasTests(TestCase):
  def setUp(self):
    self.fulfillment = Fulfillment.objects.create(slug="test-ff-alias", name="Test FF")
    self.seller = Seller.objects.create(
      company_name="Alias Seller",
      fulfillment=self.fulfillment,
      wb_api_token_encrypted="dummy",
    )
    self.cell = Cell.objects.create(
      seller=self.seller,
      number="1",
      is_occupied=True,
      marketplace=WB,
    )
    self.product = Product.objects.create(
      seller=self.seller,
      cell=self.cell,
      barcode="1111111111111",
      marketplace=WB,
      quantity=5,
      wb_chrt_id=9001,
    )
    ProductBarcodeAlias.objects.create(product=self.product, barcode="2222222222222")
    self.pick_list = PickList.objects.create(
      seller=self.seller,
      marketplace=WB,
      wb_warehouse_id=100,
      warehouse_name="Склад",
    )
    PickListItem.objects.create(
      pick_list=self.pick_list,
      cell=self.cell,
      product=self.product,
      barcode=self.product.barcode,
      quantity=1,
    )
    self.order = Order.objects.create(
      seller=self.seller,
      wb_order_id=555001,
      barcode="1111111111111",
      product=self.product,
      pick_list=self.pick_list,
      wb_warehouse_id=100,
      status=Order.Status.IN_PICKING,
      wb_supplier_status="confirm",
      has_sticker=True,
      sticker_file="dGVzdA==",
    )

  def test_resolve_product_by_primary_and_alias(self):
    self.assertEqual(
      resolve_product_by_barcode(self.seller, WB, "1111111111111"),
      self.product,
    )
    self.assertEqual(
      resolve_product_by_barcode(self.seller, WB, "2222222222222"),
      self.product,
    )

  def test_products_by_barcodes_includes_alias(self):
    mapping = _products_by_barcode(self.seller, {"2222222222222"})
    self.assertEqual(mapping["2222222222222"], self.product)

  def test_scan_allowed_in_pick_list_with_alias(self):
    self.assertTrue(_scan_allowed_in_pick_list(self.pick_list, "2222222222222"))

  def test_match_order_by_scan_with_alias(self):
    qs = Order.objects.filter(pk=self.order.pk)
    matched = _match_order_by_scan(qs, "2222222222222", seller=self.seller)
    self.assertEqual(matched, self.order)

  def test_scan_order_barcode_with_alias(self):
    result = scan_order_barcode(self.seller, "2222222222222")
    self.assertEqual(result["order"].id, self.order.id)

  def test_relink_order_with_second_barcode(self):
    orphan = Order.objects.create(
      seller=self.seller,
      wb_order_id=555002,
      barcode="2222222222222",
      wb_warehouse_id=100,
      status=Order.Status.IN_PICKING,
      wb_supplier_status="confirm",
    )
    self.assertIsNone(orphan.product_id)
    linked = relink_orders_to_products_for_seller(self.seller)
    self.assertEqual(linked, 1)
    orphan.refresh_from_db()
    self.assertEqual(orphan.product_id, self.product.id)

  def test_resolve_product_by_gtin14_leading_zero(self):
    ean_product = Product.objects.create(
      seller=self.seller,
      cell=self.cell,
      barcode="4660727916563",
      marketplace=WB,
      quantity=3,
    )
    resolved = resolve_product_by_barcode(self.seller, WB, "04660727916563")
    self.assertEqual(resolved, ean_product)

  def test_products_by_barcodes_gtin14(self):
    Product.objects.create(
      seller=self.seller,
      cell=self.cell,
      barcode="4660727916563",
      marketplace=WB,
      quantity=3,
    )
    mapping = _products_by_barcode(self.seller, {"04660727916563"})
    self.assertEqual(mapping["04660727916563"].barcode, "4660727916563")

  def test_resolve_second_sku_by_wb_chrt_id(self):
    product = Product.objects.create(
      seller=self.seller,
      cell=self.cell,
      barcode="4628529294012",
      marketplace=WB,
      quantity=4,
    )
    chrt_id = 88001
    catalog_index = {
      "4628529294012": CatalogBarcodeItem(
        barcode="4628529294012",
        wb_nm_id=100,
        vendor_code="art-1",
        title="Test",
        tech_size="M",
        wb_size="48",
        photo_url="",
        requires_marking=False,
        wb_chrt_id=chrt_id,
      ),
      "04628529294012": CatalogBarcodeItem(
        barcode="04628529294012",
        wb_nm_id=100,
        vendor_code="art-1",
        title="Test",
        tech_size="M",
        wb_size="48",
        photo_url="",
        requires_marking=False,
        wb_chrt_id=chrt_id,
      ),
    }
    chrt_map = build_wb_chrt_product_map(self.seller, catalog_index=catalog_index)
    resolved = resolve_product_by_barcode(
      self.seller,
      WB,
      "04628529294012",
      catalog_index=catalog_index,
      chrt_product_map=chrt_map,
    )
    self.assertEqual(resolved, product)
