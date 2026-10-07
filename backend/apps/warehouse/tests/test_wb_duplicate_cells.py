from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import Fulfillment
from apps.integrations.marketplace import WB
from apps.sellers.models import Seller
from apps.warehouse.models import Cell, Product, ProductBarcodeAlias
from apps.warehouse.services.catalog_fetch import CatalogBarcodeItem
from apps.warehouse.services.wb_duplicate_cells import (
  duplicate_meta_by_product_id,
  find_wb_duplicate_cell_groups,
  merge_wb_duplicate_products,
)

User = get_user_model()


class WbDuplicateCellsTests(TestCase):
  def setUp(self):
    self.fulfillment = Fulfillment.objects.create(slug="ff-dup", name="FF")
    self.user = User.objects.create_user(username="mgr", password="x")
    self.seller = Seller.objects.create(
      company_name="Dup Seller",
      fulfillment=self.fulfillment,
      wb_api_token_encrypted="t",
    )
    self.cell_a = Cell.objects.create(seller=self.seller, number="1", marketplace=WB)
    self.cell_b = Cell.objects.create(seller=self.seller, number="2", marketplace=WB)
    self.chrt_id = 70001
    self.catalog_index = {
      "1111111111111": CatalogBarcodeItem(
        barcode="1111111111111",
        wb_nm_id=10,
        vendor_code="v",
        title="T",
        tech_size="M",
        wb_size="48",
        photo_url="",
        requires_marking=False,
        wb_chrt_id=self.chrt_id,
      ),
      "2222222222222": CatalogBarcodeItem(
        barcode="2222222222222",
        wb_nm_id=10,
        vendor_code="v",
        title="T",
        tech_size="M",
        wb_size="48",
        photo_url="",
        requires_marking=False,
        wb_chrt_id=self.chrt_id,
      ),
    }
    self.product_main = Product.objects.create(
      seller=self.seller,
      cell=self.cell_a,
      barcode="1111111111111",
      marketplace=WB,
      quantity=3,
      wb_chrt_id=self.chrt_id,
    )
    self.product_jitin = Product.objects.create(
      seller=self.seller,
      cell=self.cell_b,
      barcode="2222222222222",
      marketplace=WB,
      quantity=2,
      wb_chrt_id=self.chrt_id,
    )

  def test_find_duplicate_groups(self):
    groups = find_wb_duplicate_cell_groups(self.seller, catalog_index=self.catalog_index)
    self.assertEqual(len(groups), 1)
    self.assertEqual(set(groups[0]["cell_numbers"]), {"1", "2"})

  def test_duplicate_meta_by_product(self):
    meta = duplicate_meta_by_product_id(self.seller, catalog_index=self.catalog_index)
    self.assertTrue(meta[self.product_main.id]["has_duplicate_cells"])
    self.assertIn("2", meta[self.product_main.id]["duplicate_cell_numbers"])

  def test_merge_into_main(self):
    merge_wb_duplicate_products(
      self.seller,
      target_product_id=self.product_main.id,
      user=self.user,
      catalog_index=self.catalog_index,
    )
    self.product_main.refresh_from_db()
    self.assertEqual(self.product_main.quantity, 5)
    self.assertFalse(Product.objects.filter(pk=self.product_jitin.pk).exists())
    self.assertTrue(
      ProductBarcodeAlias.objects.filter(
        product=self.product_main,
        barcode="2222222222222",
      ).exists()
    )
