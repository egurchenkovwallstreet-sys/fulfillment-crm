from io import BytesIO
from unittest.mock import patch

from django.test import TestCase

from apps.accounts.models import Fulfillment
from apps.sellers.models import Seller, SellerWarehouse
from apps.warehouse.models import Cell, Product
from apps.warehouse.services.stock_file_import import (
  apply_stock_import,
  build_stock_import_preview,
  parse_stock_excel,
)

try:
  from openpyxl import Workbook
except ImportError:  # pragma: no cover
  Workbook = None


class StockFileImportCellTests(TestCase):
  def setUp(self):
    if Workbook is None:
      self.skipTest("openpyxl not installed")
    self.fulfillment = Fulfillment.objects.create(slug="test-ff", name="Test FF")
    self.seller = Seller.objects.create(
      company_name="Import Seller",
      fulfillment=self.fulfillment,
      wb_enabled=True,
      wb_api_token_encrypted="enc",
    )
    self.warehouse = SellerWarehouse.objects.create(
      seller=self.seller,
      wb_warehouse_id=1001,
      name="WH-1",
      is_enabled=True,
    )
    self.catalog_item = type(
      "CatalogItem",
      (),
      {
        "title": "Test product",
        "requires_marking": False,
        "wb_nm_id": 123,
        "vendor_code": "V1",
        "tech_size": "M",
        "wb_size": "48",
        "photo_url": "",
      },
    )()

  def _build_excel(self, rows: list[tuple]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Баркод", "Количество", "Ячейка"])
    for row in rows:
      sheet.append(list(row))
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()

  def test_parse_stock_excel_reads_third_column_as_cell(self):
    file_bytes = self._build_excel([
      ("4601111111111", 5, 12),
      ("4602222222222", 3, "15"),
    ])
    parsed = parse_stock_excel(file_bytes)
    by_barcode = {row.barcode: row for row in parsed}
    self.assertEqual(by_barcode["4601111111111"].cell_number, "12")
    self.assertEqual(by_barcode["4602222222222"].cell_number, "15")

  @patch("apps.warehouse.services.stock_file_import.fetch_wb_stocks_for_warehouses")
  @patch("apps.warehouse.services.stock_file_import.build_catalog_index_for_barcodes")
  def test_preview_shows_target_cell_from_excel(self, mock_catalog, mock_wb_stocks):
    mock_catalog.return_value = {"4601111111111": self.catalog_item}
    mock_wb_stocks.return_value = {"4601111111111": {"total": 0}}
    file_bytes = self._build_excel([("4601111111111", 4, 7)])

    preview = build_stock_import_preview(
      self.seller,
      warehouse_id=self.warehouse.id,
      file_bytes=file_bytes,
    )

    self.assertEqual(len(preview["rows"]), 1)
    row = preview["rows"][0]
    self.assertEqual(row["cell_number"], "7")
    self.assertTrue(row["will_create_cell"])

  @patch("apps.warehouse.services.stock_file_import.fetch_wb_stocks_for_warehouses")
  @patch("apps.warehouse.services.stock_file_import.set_wb_stocks_absolute_batch")
  @patch("apps.warehouse.services.stock_file_import.build_catalog_index_for_barcodes")
  def test_apply_creates_cell_and_assigns_product(
    self,
    mock_catalog,
    mock_push_batch,
    mock_wb_stocks,
  ):
    mock_catalog.return_value = {"4601111111111": self.catalog_item}
    mock_wb_stocks.side_effect = [
      {"4601111111111": {"total": 0}},
      {"4601111111111": {"total": 4}},
      {"4601111111111": {"total": 4}},
    ]
    file_bytes = self._build_excel([("4601111111111", 4, 9)])
    preview = build_stock_import_preview(
      self.seller,
      warehouse_id=self.warehouse.id,
      file_bytes=file_bytes,
    )

    result = apply_stock_import(
      self.seller,
      warehouse_id=self.warehouse.id,
      rows=preview["rows"],
    )

    self.assertEqual(result["applied"], 1)
    product = Product.objects.get(seller=self.seller, barcode="4601111111111")
    self.assertEqual(product.cell.number, "9")
    self.assertEqual(product.quantity, 4)
    self.assertTrue(Cell.objects.filter(seller=self.seller, number="9").exists())
    mock_push_batch.assert_called_once()
    pushed = mock_push_batch.call_args[0][2]
    self.assertEqual(pushed[0][0], "4601111111111")
    self.assertEqual(pushed[0][1], 4)

  @patch("apps.warehouse.services.stock_file_import.fetch_wb_stocks_for_warehouses")
  @patch("apps.warehouse.services.stock_file_import.set_wb_stocks_absolute_batch")
  @patch("apps.warehouse.services.stock_file_import.build_catalog_index_for_barcodes")
  def test_apply_moves_existing_product_to_excel_cell(
    self,
    mock_catalog,
    mock_push_batch,
    mock_wb_stocks,
  ):
    mock_catalog.return_value = {"4601111111111": self.catalog_item}
    mock_wb_stocks.side_effect = [
      {"4601111111111": {"total": 2}},
      {"4601111111111": {"total": 4}},
      {"4601111111111": {"total": 4}},
    ]
    old_cell = Cell.objects.create(seller=self.seller, number="1", is_occupied=True)
    Product.objects.create(
      seller=self.seller,
      barcode="4601111111111",
      name="Old",
      cell=old_cell,
      quantity=1,
    )
    preview_rows = [{
      "barcode": "4601111111111",
      "add_quantity": 2,
      "cell_number": "22",
    }]

    apply_stock_import(
      self.seller,
      warehouse_id=self.warehouse.id,
      rows=preview_rows,
    )

    product = Product.objects.get(seller=self.seller, barcode="4601111111111")
    old_cell.refresh_from_db()
    self.assertEqual(product.cell.number, "22")
    self.assertEqual(product.quantity, 3)
    self.assertFalse(old_cell.is_occupied)
    mock_push_batch.assert_called_once()
    self.assertEqual(mock_push_batch.call_args[0][2][0][1], 4)
