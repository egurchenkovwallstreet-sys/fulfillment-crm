from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase

from apps.accounts.models import Fulfillment
from apps.sellers.models import Seller, SellerWarehouse
from apps.warehouse.models import Cell, Product
from apps.warehouse.services.catalog_fetch import CatalogBarcodeItem, _parse_cards_to_items
from apps.warehouse.services.product_catalog import resolve_wb_chrt_id_for_barcode
from apps.warehouse.services.wb_stocks import (
  WBStockError,
  _format_wb_stock_error,
  set_wb_stocks_absolute_batch,
)
from apps.integrations.wb_client import WBApiError


class WbChrtParseTests(SimpleTestCase):
  def test_parse_card_extracts_chrt_id(self):
    card = {
      "nmID": 123,
      "title": "Test",
      "sizes": [{
        "chrtID": 987654,
        "techSize": "42",
        "wbSize": "42",
        "skus": ["4601111111111"],
      }],
    }
    items = _parse_cards_to_items([card])
    self.assertEqual(len(items), 1)
    self.assertEqual(items[0].wb_chrt_id, 987654)


class WbStockErrorFormatTests(SimpleTestCase):
  def test_not_found_message(self):
    exc = WBApiError(
      '409: [{"code":"NotFound","message":"Not found"}]',
      status_code=409,
      payload=[{"code": "NotFound", "message": "Not found"}],
    )
    text = _format_wb_stock_error(exc, barcode="4601111111111")
    self.assertIn("не нашёл", text.lower())

  def test_cargo_restriction_message_names_warehouse(self):
    exc = WBApiError(
      '409: [{"code":"CargoWarehouseRestriction","message":"LCL"}]',
      status_code=409,
      payload=[{"code": "CargoWarehouseRestriction", "message": "LCL"}],
    )
    warehouse = SellerWarehouse(name="ФФ Центр")
    text = _format_wb_stock_error(exc, warehouse=warehouse)
    self.assertIn("ФФ Центр", text)
    self.assertIn("другой FBS-склад", text)


class WbChrtResolveTests(TestCase):
  def setUp(self):
    self.fulfillment = Fulfillment.objects.create(slug="chrt-ff2", name="Chrt FF2")
    self.seller = Seller.objects.create(
      company_name="Chrt Seller 2",
      fulfillment=self.fulfillment,
      wb_api_token_encrypted="token",
    )

  @patch("apps.warehouse.services.product_catalog.lookup_catalog_item_for_barcode")
  def test_resolve_prefers_live_catalog_over_stale_product(self, lookup_mock):
    cell = Cell.objects.create(seller=self.seller, number="1")
    product = Product.objects.create(
      seller=self.seller,
      barcode="4601111111111",
      name="Test",
      quantity=1,
      cell=cell,
      wb_chrt_id=111111,
    )
    lookup_mock.return_value = CatalogBarcodeItem(
      barcode="4601111111111",
      wb_nm_id=123,
      vendor_code="v",
      title="Test",
      tech_size="42",
      wb_size="42",
      photo_url="",
      requires_marking=False,
      wb_chrt_id=987654,
    )
    chrt_id = resolve_wb_chrt_id_for_barcode(
      self.seller,
      "4601111111111",
      product=product,
    )
    self.assertEqual(chrt_id, 987654)
    product.refresh_from_db()
    self.assertEqual(product.wb_chrt_id, 987654)


class WbStockPushTests(TestCase):
  def setUp(self):
    self.fulfillment = Fulfillment.objects.create(slug="chrt-ff", name="Chrt FF")
    self.seller = Seller.objects.create(
      company_name="Chrt Seller",
      fulfillment=self.fulfillment,
      wb_api_token_encrypted="token",
    )
    self.warehouse = SellerWarehouse.objects.create(
      seller=self.seller,
      wb_warehouse_id=555001,
      name="FBS Test",
    )

  @patch("apps.warehouse.services.wb_stocks._get_wb_client")
  @patch("apps.warehouse.services.wb_stocks._resolve_chrt_id", return_value=987654)
  def test_set_wb_stocks_uses_chrt_id(self, _resolve_mock, client_mock):
    client = MagicMock()
    client_mock.return_value = client
    pushed = set_wb_stocks_absolute_batch(
      self.seller,
      self.warehouse,
      [("4601111111111", 50)],
    )
    self.assertEqual(pushed, 1)
    client.update_warehouse_stocks.assert_called_once_with(
      555001,
      [{"chrtId": 987654, "amount": 50}],
    )
