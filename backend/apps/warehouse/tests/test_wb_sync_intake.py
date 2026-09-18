from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase

from apps.accounts.models import Fulfillment
from apps.sellers.models import Seller, SellerWarehouse
from apps.warehouse.models import Cell, Product
from apps.warehouse.services.catalog_fetch import CatalogBarcodeItem
from apps.warehouse.services.wb_sync_intake import (
  apply_wb_sync_auto,
  preview_wb_sync_intake,
)


class WbSyncIntakeTests(TestCase):
  def setUp(self):
    cache.clear()
    self.fulfillment = Fulfillment.objects.create(slug="wb-sync-ff", name="WB Sync FF")
    self.seller = Seller.objects.create(
      company_name="WB Sync Seller",
      fulfillment=self.fulfillment,
      wb_api_token_encrypted="token",
    )
    self.warehouse = SellerWarehouse.objects.create(
      seller=self.seller,
      wb_warehouse_id=12345,
      name="FBS Test",
      is_enabled=True,
    )

  @patch("apps.warehouse.services.wb_sync_intake.fetch_wb_stocks_for_warehouses")
  @patch("apps.warehouse.services.wb_sync_intake.fetch_seller_catalog_items")
  def test_preview_only_items_with_stock(self, mock_catalog, mock_stocks):
    mock_catalog.return_value = [
      CatalogBarcodeItem(
        barcode="111",
        wb_nm_id=1,
        vendor_code="A",
        title="Товар 1",
        tech_size="M",
        wb_size="48",
        photo_url="",
        requires_marking=False,
      ),
      CatalogBarcodeItem(
        barcode="222",
        wb_nm_id=2,
        vendor_code="B",
        title="Товар 2",
        tech_size="L",
        wb_size="50",
        photo_url="",
        requires_marking=False,
      ),
    ]
    mock_stocks.return_value = {
      "111": {"total": 5, "by_warehouse": {self.warehouse.id: 5}},
      "222": {"total": 0, "by_warehouse": {self.warehouse.id: 0}},
    }

    result = preview_wb_sync_intake(self.seller, self.warehouse.id)

    self.assertEqual(len(result.items), 1)
    self.assertEqual(result.items[0].barcode, "111")
    self.assertEqual(result.items[0].wb_stock, 5)
    self.assertEqual(result.items[0].cell_number, "1")
    mock_stocks.assert_called_once()

  @patch("apps.warehouse.services.wb_sync_intake.fetch_wb_stocks_for_warehouses")
  @patch("apps.warehouse.services.wb_sync_intake.fetch_seller_catalog_items")
  def test_apply_uses_preview_cache_without_second_catalog_fetch(
    self,
    mock_catalog,
    mock_stocks,
  ):
    mock_catalog.return_value = [
      CatalogBarcodeItem(
        barcode="111",
        wb_nm_id=1,
        vendor_code="A",
        title="Товар 1",
        tech_size="M",
        wb_size="48",
        photo_url="",
        requires_marking=False,
      ),
    ]
    mock_stocks.return_value = {
      "111": {"total": 3, "by_warehouse": {self.warehouse.id: 3}},
    }

    preview_wb_sync_intake(self.seller, self.warehouse.id)
    mock_catalog.reset_mock()
    mock_stocks.reset_mock()

    cell = Cell.objects.create(seller=self.seller, marketplace="wb", number="5")
    product = Product.objects.create(
      seller=self.seller,
      marketplace="wb",
      barcode="111",
      cell=cell,
      quantity=0,
      name="Old",
    )

    result = apply_wb_sync_auto(self.seller, self.warehouse.id, barcodes=["111"])

    mock_catalog.assert_not_called()
    mock_stocks.assert_not_called()
    product.refresh_from_db()
    self.assertEqual(result.updated, 1)
    self.assertEqual(product.quantity, 3)
