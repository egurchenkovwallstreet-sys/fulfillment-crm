from unittest.mock import patch

from django.test import TestCase

from apps.accounts.models import Fulfillment
from apps.integrations.marketplace import WB
from apps.sellers.models import Seller
from apps.warehouse.models import Cell, Product, ProductBarcodeAlias
from apps.warehouse.services.catalog_fetch import CatalogBarcodeItem
from apps.warehouse.services.wb_barcode_alias_sync import (
  sync_wb_barcode_aliases_from_index,
)


class WbBarcodeAliasSyncTests(TestCase):
  def setUp(self):
    self.fulfillment = Fulfillment.objects.create(slug="ff-alias-sync", name="FF")
    self.seller = Seller.objects.create(
      company_name="Sync Seller",
      fulfillment=self.fulfillment,
      wb_api_token_encrypted="dummy",
    )
    self.cell = Cell.objects.create(
      seller=self.seller,
      number="A1",
      marketplace=WB,
    )
    self.product = Product.objects.create(
      seller=self.seller,
      cell=self.cell,
      barcode="4628529294012",
      marketplace=WB,
      quantity=5,
    )
    self.chrt_id = 88001
    self.catalog_index = {
      "4628529294012": CatalogBarcodeItem(
        barcode="4628529294012",
        wb_nm_id=100,
        vendor_code="art-1",
        title="Test",
        tech_size="M",
        wb_size="48",
        photo_url="",
        requires_marking=False,
        wb_chrt_id=self.chrt_id,
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
        wb_chrt_id=self.chrt_id,
      ),
    }

  def test_sync_from_index_registers_second_sku_as_alias(self):
    result = sync_wb_barcode_aliases_from_index(self.seller, self.catalog_index)

    self.assertEqual(result.aliases_added, 1)
    self.product.refresh_from_db()
    self.assertEqual(self.product.wb_chrt_id, self.chrt_id)
    aliases = list(
      ProductBarcodeAlias.objects.filter(product=self.product).values_list("barcode", flat=True)
    )
    self.assertIn("04628529294012", aliases)

  @patch(
    "apps.warehouse.services.wb_barcode_alias_sync.build_seller_catalog_index",
  )
  def test_sync_for_seller_uses_force_refresh(self, mock_build):
    mock_build.return_value = self.catalog_index
    from apps.warehouse.services.wb_barcode_alias_sync import sync_wb_barcode_aliases_for_seller

    result = sync_wb_barcode_aliases_for_seller(self.seller)

    mock_build.assert_called_once_with(self.seller, force_refresh=True)
    self.assertEqual(result.aliases_added, 1)
