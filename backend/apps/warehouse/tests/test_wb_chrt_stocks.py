from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase

from apps.accounts.models import Fulfillment
from apps.sellers.models import Seller, SellerWarehouse
from apps.warehouse.services.catalog_fetch import CatalogBarcodeItem, _parse_cards_to_items
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
    text = _format_wb_stock_error(exc)
    self.assertIn("chrtId", text)


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
