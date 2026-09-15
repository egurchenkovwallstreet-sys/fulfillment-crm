"""Импорт остатков из Excel (формат WB): баркод + количество + ячейка."""
from __future__ import annotations

import re
from dataclasses import dataclass
from io import BytesIO

from django.db import transaction

from apps.integrations.marketplace import WB
from apps.integrations.models import AuditLog
from apps.sellers.models import Seller
from apps.warehouse.models import Cell, Product, ProductWarehouseStock, StockOperation
from apps.warehouse.services.catalog_fetch import CatalogError, build_seller_catalog_index
from apps.warehouse.services.cells import (
  create_cell_with_next_number,
  get_or_create_cell_by_number,
  refresh_cell_occupied,
)
from apps.warehouse.services.stock_balance import (
  compute_wb_amount_from_crm,
  count_reserved_new_orders,
)
from apps.warehouse.services.wb_stocks import (
  WBStockError,
  fetch_wb_stock_for_barcode,
  fetch_wb_stocks_for_warehouses,
  get_seller_warehouse,
  increment_product_warehouse_stock,
  push_wb_stock_absolute,
  push_wb_stock_increment,
)

try:
  from openpyxl import load_workbook
except ImportError:  # pragma: no cover
  load_workbook = None


class StockFileImportError(Exception):
  pass


STOCK_IMPORT_MODE_INCREMENT = "increment"
STOCK_IMPORT_MODE_SET_MINUS_NEW = "set_minus_new"
STOCK_IMPORT_MODES = {STOCK_IMPORT_MODE_INCREMENT, STOCK_IMPORT_MODE_SET_MINUS_NEW}


BARCODE_HEADERS = {
  "баркод", "barcode", "sku", "штрихкод", "штрих-код", "штрих код",
}
QTY_HEADERS = {
  "количество", "кол-во", "кол во", "колво", "amount", "qty", "остаток", "quantity",
}
CELL_HEADERS = {
  "ячейка",
  "cell",
  "номер ячейки",
  "№ ячейки",
  "no ячейки",
  "место",
  "яч",
}


@dataclass
class ParsedStockRow:
  barcode: str
  add_quantity: int
  cell_number: str = ""


@dataclass
class StockImportPreviewRow:
  barcode: str
  add_quantity: int
  status: str
  title: str
  crm_before: int
  crm_after: int
  wb_before: int
  wb_after: int
  reserved_new: int
  will_create: bool
  cell_number: str
  cell_number_before: str
  will_create_cell: bool
  message: str


def _normalize_header(value) -> str:
  text = str(value or "").strip().lower()
  text = text.replace("\xa0", " ")
  return re.sub(r"\s+", " ", text)


def _parse_quantity(value) -> int | None:
  if value is None or value == "":
    return None
  if isinstance(value, (int, float)):
    qty = int(value)
    return qty if qty > 0 else None
  text = str(value).strip().replace(",", ".")
  if not text:
    return None
  try:
    qty = int(float(text))
  except ValueError:
    return None
  return qty if qty > 0 else None


def _parse_cell_number(value) -> str:
  if value is None or value == "":
    return ""
  if isinstance(value, (int, float)):
    if float(value).is_integer():
      return str(int(value))
    return str(value).strip()
  text = str(value).strip()
  if re.fullmatch(r"\d+\.0+", text):
    return str(int(float(text)))
  return text


def _detect_cell_column(headers: list[str], barcode_col: int, qty_col: int) -> int | None:
  cell_candidates = [i for i, h in enumerate(headers) if h in CELL_HEADERS]
  if cell_candidates:
    return cell_candidates[0]
  fallback = 2
  if fallback not in {barcode_col, qty_col} and fallback < len(headers):
    return fallback
  return None


def parse_stock_excel(file_bytes: bytes) -> list[ParsedStockRow]:
  if load_workbook is None:
    raise StockFileImportError("На сервере не установлен openpyxl для чтения Excel")

  try:
    workbook = load_workbook(BytesIO(file_bytes), read_only=True, data_only=True)
  except Exception as exc:
    raise StockFileImportError(f"Не удалось прочитать Excel: {exc}") from exc

  sheet = workbook.active
  rows = list(sheet.iter_rows(values_only=True))
  if not rows:
    raise StockFileImportError("Файл пустой")

  header_idx = None
  barcode_col = None
  qty_col = None
  cell_col = None

  for idx, row in enumerate(rows[:20]):
    headers = [_normalize_header(cell) for cell in row]
    bc_candidates = [i for i, h in enumerate(headers) if h in BARCODE_HEADERS]
    qty_candidates = [i for i, h in enumerate(headers) if h in QTY_HEADERS]
    if bc_candidates and qty_candidates:
      header_idx = idx
      barcode_col = bc_candidates[0]
      qty_col = qty_candidates[0]
      cell_col = _detect_cell_column(headers, barcode_col, qty_col)
      break

  if header_idx is None or barcode_col is None or qty_col is None:
    raise StockFileImportError(
      "Не найдены колонки «Баркод» и «Количество». Используйте выгрузку остатков WB."
    )

  aggregated: dict[str, ParsedStockRow] = {}
  for row in rows[header_idx + 1:]:
    if not row:
      continue
    barcode = str(row[barcode_col] or "").strip()
    qty = _parse_quantity(row[qty_col] if qty_col < len(row) else None)
    cell_number = ""
    if cell_col is not None and cell_col < len(row):
      cell_number = _parse_cell_number(row[cell_col])
    if not barcode or qty is None:
      continue
    existing = aggregated.get(barcode)
    if existing:
      existing.add_quantity += qty
      if cell_number:
        existing.cell_number = cell_number
    else:
      aggregated[barcode] = ParsedStockRow(
        barcode=barcode,
        add_quantity=qty,
        cell_number=cell_number,
      )

  if not aggregated:
    raise StockFileImportError("В файле нет строк с баркодом и количеством")

  return sorted(aggregated.values(), key=lambda item: item.barcode)


def _get_crm_warehouse_qty(product: Product | None, warehouse) -> int:
  if not product:
    return 0
  pws = ProductWarehouseStock.objects.filter(
    product=product,
    seller_warehouse=warehouse,
  ).first()
  return int(pws.quantity) if pws else 0


def _normalize_import_mode(mode: str | None) -> str:
  normalized = (mode or STOCK_IMPORT_MODE_INCREMENT).strip()
  if normalized not in STOCK_IMPORT_MODES:
    raise StockFileImportError(
      f"Неизвестный режим импорта: {normalized}. "
      f"Доступны: {STOCK_IMPORT_MODE_INCREMENT}, {STOCK_IMPORT_MODE_SET_MINUS_NEW}",
    )
  return normalized


def _preview_row_values(
  *,
  mode: str,
  seller: Seller,
  row: ParsedStockRow,
  product: Product | None,
  crm_wh_before: int,
  wb_before: int,
) -> tuple[int, int, int, str]:
  reserved_new = 0
  if mode == STOCK_IMPORT_MODE_SET_MINUS_NEW:
    reserved_new = count_reserved_new_orders(seller, row.barcode)
    crm_after = row.add_quantity
    wb_after, restock = compute_wb_amount_from_crm(row.add_quantity, reserved_new)
    message = ""
    if restock:
      message = f"«Новых» ({reserved_new}) больше остатка из файла — на WB будет 0"
    return crm_after, wb_after, reserved_new, message

  crm_before = product.quantity if product else 0
  return (
    crm_before + row.add_quantity,
    wb_before + row.add_quantity,
    reserved_new,
    "",
  )


def _resolve_import_cell(
  seller: Seller,
  *,
  cell_number: str,
  existing_cells: dict[str, Cell],
) -> Cell:
  normalized = _parse_cell_number(cell_number)
  if not normalized:
    cell = create_cell_with_next_number(seller)
    existing_cells[cell.number] = cell
    return cell
  if normalized in existing_cells:
    return existing_cells[normalized]
  cell = get_or_create_cell_by_number(seller, normalized)
  existing_cells[normalized] = cell
  return cell


def _cell_will_be_created(seller: Seller, cell_number: str, existing_cells: dict[str, Cell]) -> bool:
  normalized = _parse_cell_number(cell_number)
  if not normalized:
    return True
  if normalized in existing_cells:
    return False
  return not Cell.objects.filter(seller=seller, marketplace=WB, number=normalized).exists()


def _assign_product_cell(product: Product, cell: Cell) -> Cell | None:
  old_cell = product.cell if product.cell_id else None
  if product.cell_id == cell.id:
    return None
  product.cell = cell
  return old_cell


def _refresh_cells_after_assign(new_cell: Cell, old_cell: Cell | None) -> None:
  refresh_cell_occupied(new_cell)
  if old_cell and old_cell.pk != new_cell.pk:
    refresh_cell_occupied(old_cell)


def build_stock_import_preview(
  seller: Seller,
  *,
  warehouse_id: int,
  file_bytes: bytes,
  mode: str = STOCK_IMPORT_MODE_INCREMENT,
) -> dict:
  mode = _normalize_import_mode(mode)
  warehouse = get_seller_warehouse(seller, warehouse_id)
  parsed_rows = parse_stock_excel(file_bytes)
  file_units = sum(row.add_quantity for row in parsed_rows)

  try:
    catalog_index = build_seller_catalog_index(seller)
  except CatalogError as exc:
    raise StockFileImportError(str(exc)) from exc

  crm_products = {
    p.barcode: p
    for p in Product.objects.filter(seller=seller).select_related("cell")
  }
  existing_cells = {
    cell.number: cell
    for cell in Cell.objects.filter(seller=seller, marketplace=WB)
  }

  known_barcodes = [row.barcode for row in parsed_rows if row.barcode in catalog_index]
  try:
    wb_stock_map = fetch_wb_stocks_for_warehouses(seller, [warehouse], known_barcodes)
  except WBStockError as exc:
    raise StockFileImportError(str(exc)) from exc

  preview_rows: list[StockImportPreviewRow] = []
  skipped_unknown_details: list[dict] = []

  for row in parsed_rows:
    catalog_item = catalog_index.get(row.barcode)
    if not catalog_item:
      skipped_unknown_details.append({
        "barcode": row.barcode,
        "add_quantity": row.add_quantity,
      })
      continue

    product = crm_products.get(row.barcode)
    crm_before = product.quantity if product else 0
    crm_wh_before = _get_crm_warehouse_qty(product, warehouse)
    wb_before = int((wb_stock_map.get(row.barcode) or {}).get("total") or 0)
    crm_after, wb_after, reserved_new, message = _preview_row_values(
      mode=mode,
      seller=seller,
      row=row,
      product=product,
      crm_wh_before=crm_wh_before,
      wb_before=wb_before,
    )
    if mode == STOCK_IMPORT_MODE_SET_MINUS_NEW:
      crm_before = product.quantity if product else 0

    target_cell_number = _parse_cell_number(row.cell_number)
    cell_number_before = product.cell.number if product and product.cell_id else ""
    will_create_cell = _cell_will_be_created(seller, target_cell_number, existing_cells)
    if target_cell_number and not will_create_cell:
      existing_cells.setdefault(target_cell_number, Cell.objects.get(
        seller=seller,
        marketplace=WB,
        number=target_cell_number,
      ))

    preview_rows.append(
      StockImportPreviewRow(
        barcode=row.barcode,
        add_quantity=row.add_quantity,
        status="ok",
        title=catalog_item.title,
        crm_before=crm_before,
        crm_after=crm_after,
        wb_before=wb_before,
        wb_after=wb_after,
        reserved_new=reserved_new,
        will_create=product is None,
        cell_number=target_cell_number,
        cell_number_before=cell_number_before,
        will_create_cell=will_create_cell,
        message=message,
      ),
    )

  return {
    "mode": mode,
    "warehouse": {
      "id": warehouse.id,
      "wb_warehouse_id": warehouse.wb_warehouse_id,
      "name": warehouse.name,
    },
    "rows": [_serialize_preview_row(row) for row in preview_rows],
    "skipped_unknown": [item["barcode"] for item in skipped_unknown_details],
    "skipped_unknown_details": skipped_unknown_details,
    "totals": {
      "file_barcodes": len(parsed_rows),
      "file_units": file_units,
      "to_apply": len(preview_rows),
      "skipped_unknown": len(skipped_unknown_details),
      "skipped_units": sum(item["add_quantity"] for item in skipped_unknown_details),
      "new_products": sum(1 for row in preview_rows if row.will_create),
      "add_units": sum(row.add_quantity for row in preview_rows),
    },
  }


def _serialize_preview_row(row: StockImportPreviewRow) -> dict:
  return {
    "barcode": row.barcode,
    "add_quantity": row.add_quantity,
    "status": row.status,
    "title": row.title,
    "crm_before": row.crm_before,
    "crm_after": row.crm_after,
    "wb_before": row.wb_before,
    "wb_after": row.wb_after,
    "reserved_new": row.reserved_new,
    "will_create": row.will_create,
    "cell_number": row.cell_number,
    "cell_number_before": row.cell_number_before,
    "will_create_cell": row.will_create_cell,
    "message": row.message,
  }


def _serialize_mismatch(item: dict) -> dict:
  return {
    "barcode": item["barcode"],
    "add_quantity": item["add_quantity"],
    "crm_before": item["crm_before"],
    "crm_expected": item["crm_expected"],
    "crm_actual": item["crm_actual"],
    "wb_before": item["wb_before"],
    "wb_expected": item["wb_expected"],
    "wb_actual": item["wb_actual"],
    "error": item["error"],
    "stage": item["stage"],
  }


@transaction.atomic
def apply_stock_import(
  seller: Seller,
  *,
  warehouse_id: int,
  rows: list[dict],
  mode: str = STOCK_IMPORT_MODE_INCREMENT,
  user=None,
) -> dict:
  mode = _normalize_import_mode(mode)
  warehouse = get_seller_warehouse(seller, warehouse_id)
  if not rows:
    raise StockFileImportError("Нет строк для применения")

  try:
    catalog_index = build_seller_catalog_index(seller)
  except CatalogError as exc:
    raise StockFileImportError(str(exc)) from exc

  aggregated: dict[str, ParsedStockRow] = {}
  for row in rows:
    barcode = str(row.get("barcode") or "").strip()
    try:
      qty = int(row.get("add_quantity") or 0)
    except (TypeError, ValueError):
      qty = 0
    cell_number = _parse_cell_number(row.get("cell_number"))
    if not barcode or qty <= 0:
      continue
    existing = aggregated.get(barcode)
    if existing:
      existing.add_quantity += qty
      if cell_number:
        existing.cell_number = cell_number
    else:
      aggregated[barcode] = ParsedStockRow(
        barcode=barcode,
        add_quantity=qty,
        cell_number=cell_number,
      )

  if not aggregated:
    raise StockFileImportError("Нет корректных строк для применения")

  applied = 0
  created_products = 0
  verified = 0
  skipped_unknown_details: list[dict] = []
  mismatches: list[dict] = []
  existing_cells = {
    cell.number: cell
    for cell in Cell.objects.filter(seller=seller, marketplace=WB)
  }

  was_crm_units = 0
  was_wb_units = 0
  added_units = 0
  result_crm_units = 0
  result_wb_units = 0

  for barcode, parsed_row in aggregated.items():
    add_qty = parsed_row.add_quantity
    catalog_item = catalog_index.get(barcode)
    if not catalog_item:
      skipped_unknown_details.append({"barcode": barcode, "add_quantity": add_qty})
      mismatches.append({
        "barcode": barcode,
        "add_quantity": add_qty,
        "crm_before": 0,
        "crm_expected": 0,
        "crm_actual": 0,
        "wb_before": 0,
        "wb_expected": 0,
        "wb_actual": 0,
        "error": "Баркод не найден в каталоге WB селлера",
        "stage": "catalog",
      })
      continue

    product = (
      Product.objects.select_for_update()
      .filter(seller=seller, barcode=barcode)
      .select_related("cell")
      .first()
    )
    crm_before = product.quantity if product else 0
    wb_before = fetch_wb_stock_for_barcode(seller, warehouse, barcode)
    crm_wh_before = _get_crm_warehouse_qty(product, warehouse)
    reserved_new = count_reserved_new_orders(seller, barcode) if mode == STOCK_IMPORT_MODE_SET_MINUS_NEW else 0

    if mode == STOCK_IMPORT_MODE_SET_MINUS_NEW:
      crm_expected = add_qty
      wb_expected, _restock = compute_wb_amount_from_crm(add_qty, reserved_new)
      crm_wh_expected = add_qty
      crm_total_expected = add_qty
    else:
      crm_expected = crm_before + add_qty
      wb_expected = wb_before + add_qty
      crm_wh_expected = crm_wh_before + add_qty
      crm_total_expected = crm_expected

    was_crm_units += crm_before
    was_wb_units += wb_before

    savepoint = transaction.savepoint()
    created_here = False
    try:
      cell = _resolve_import_cell(
        seller,
        cell_number=parsed_row.cell_number,
        existing_cells=existing_cells,
      )

      if mode == STOCK_IMPORT_MODE_SET_MINUS_NEW:
        if product:
          old_cell = _assign_product_cell(product, cell)
          product.quantity = crm_total_expected
          product.save(update_fields=["quantity", "cell", "updated_at"])
          _refresh_cells_after_assign(cell, old_cell)
          ProductWarehouseStock.objects.update_or_create(
            product=product,
            seller_warehouse=warehouse,
            defaults={"quantity": add_qty},
          )
        else:
          product = Product.objects.create(
            seller=seller,
            barcode=barcode,
            name=catalog_item.title,
            cell=cell,
            quantity=add_qty,
            requires_marking=catalog_item.requires_marking,
            wb_nm_id=catalog_item.wb_nm_id,
            vendor_code=catalog_item.vendor_code,
            tech_size=catalog_item.tech_size,
            wb_size=catalog_item.wb_size,
            photo_url=catalog_item.photo_url,
          )
          refresh_cell_occupied(cell)
          ProductWarehouseStock.objects.update_or_create(
            product=product,
            seller_warehouse=warehouse,
            defaults={"quantity": add_qty},
          )
          created_here = True
        push_wb_stock_absolute(seller, warehouse, barcode, wb_expected)
      else:
        if product:
          old_cell = _assign_product_cell(product, cell)
          product.quantity += add_qty
          product.save(update_fields=["quantity", "cell", "updated_at"])
          _refresh_cells_after_assign(cell, old_cell)
          increment_product_warehouse_stock(product, warehouse, add_qty)
        else:
          product = Product.objects.create(
            seller=seller,
            barcode=barcode,
            name=catalog_item.title,
            cell=cell,
            quantity=add_qty,
            requires_marking=catalog_item.requires_marking,
            wb_nm_id=catalog_item.wb_nm_id,
            vendor_code=catalog_item.vendor_code,
            tech_size=catalog_item.tech_size,
            wb_size=catalog_item.wb_size,
            photo_url=catalog_item.photo_url,
          )
          refresh_cell_occupied(cell)
          increment_product_warehouse_stock(product, warehouse, add_qty)
          created_here = True
        push_wb_stock_increment(seller, warehouse, barcode, add_qty)

      product.refresh_from_db()
      crm_actual = product.quantity
      crm_wh_actual = _get_crm_warehouse_qty(product, warehouse)
      wb_actual = fetch_wb_stock_for_barcode(seller, warehouse, barcode)

      if mode == STOCK_IMPORT_MODE_SET_MINUS_NEW:
        crm_ok = crm_actual == crm_total_expected and crm_wh_actual == crm_wh_expected
      else:
        crm_ok = crm_actual == crm_expected and crm_wh_actual == crm_wh_expected
      wb_ok = wb_actual == wb_expected

      if not crm_ok and not wb_ok:
        raise StockFileImportError(
          f"CRM: ожидалось {crm_total_expected if mode == STOCK_IMPORT_MODE_SET_MINUS_NEW else crm_expected}, "
          f"получилось {crm_actual}; "
          f"WB: ожидалось {wb_expected}, получилось {wb_actual}",
        )
      if not crm_ok:
        raise StockFileImportError(
          f"CRM: ожидалось {crm_total_expected if mode == STOCK_IMPORT_MODE_SET_MINUS_NEW else crm_expected} "
          f"(склад {crm_wh_expected}), "
          f"получилось {crm_actual} (склад {crm_wh_actual})",
        )
      if not wb_ok:
        raise StockFileImportError(
          f"WB: ожидалось {wb_expected}, получилось {wb_actual}",
        )

      mode_label = (
        "установка из Excel"
        if mode == STOCK_IMPORT_MODE_SET_MINUS_NEW
        else f"Импорт Excel +{add_qty} шт."
      )
      cell_label = f", яч. {cell.number}" if cell.number else ""
      StockOperation.objects.create(
        product=product,
        operation_type=StockOperation.OperationType.INTAKE,
        quantity=add_qty,
        performed_by=user,
        comment=(
          f"{mode_label}, склад WB "
          f"{warehouse.name or warehouse.wb_warehouse_id}"
          f"{cell_label}"
          + (
            f", «Новые» −{reserved_new}, WB={wb_expected}"
            if mode == STOCK_IMPORT_MODE_SET_MINUS_NEW
            else ""
          )
        ),
      )
      transaction.savepoint_commit(savepoint)
      applied += 1
      verified += 1
      added_units += add_qty
      if created_here:
        created_products += 1
      result_crm_units += crm_actual
      result_wb_units += wb_actual
    except (WBStockError, StockFileImportError) as exc:
      transaction.savepoint_rollback(savepoint)
      if isinstance(exc, WBStockError):
        stage = "wb"
      elif "CRM" in str(exc):
        stage = "crm"
      elif "WB" in str(exc):
        stage = "wb"
      else:
        stage = "verify"

      mismatches.append({
        "barcode": barcode,
        "add_quantity": add_qty,
        "crm_before": crm_before,
        "crm_expected": crm_expected,
        "crm_actual": crm_before,
        "wb_before": wb_before,
        "wb_expected": wb_expected,
        "wb_actual": wb_before,
        "error": str(exc),
        "stage": stage,
      })
      result_crm_units += crm_before
      result_wb_units += wb_before

  file_barcodes = len(aggregated)
  file_units = sum(row.add_quantity for row in aggregated.values())

  all_ok = len(mismatches) == 0 and applied > 0

  summary = {
    "file_barcodes": file_barcodes,
    "file_units": file_units,
    "was_crm_units": was_crm_units,
    "was_wb_units": was_wb_units,
    "added_units": added_units,
    "expected_crm_units": was_crm_units + added_units,
    "expected_wb_units": was_wb_units + added_units,
    "result_crm_units": result_crm_units,
    "result_wb_units": result_wb_units,
    "applied_barcodes": applied,
    "verified_barcodes": verified,
    "failed_barcodes": len(mismatches),
  }

  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.INTAKE,
    message=(
      f"Импорт остатков Excel ({mode}): {applied}/{file_barcodes} баркодов, "
      f"+{added_units} шт., сверка {'OK' if all_ok else 'ОШИБКИ'}"
    ),
    details={
      "mode": mode,
      "warehouse_id": warehouse.id,
      "summary": summary,
      "applied": applied,
      "created_products": created_products,
      "skipped_unknown_details": skipped_unknown_details,
      "mismatches": mismatches,
      "all_ok": all_ok,
    },
  )

  if applied == 0 and mismatches:
    raise StockFileImportError(
      f"Не удалось применить ни одного баркода. Ошибок: {len(mismatches)}",
    )

  return {
    "ok": all_ok,
    "mode": mode,
    "applied": applied,
    "created_products": created_products,
    "verified": verified,
    "skipped_unknown": [item["barcode"] for item in skipped_unknown_details],
    "skipped_unknown_details": skipped_unknown_details,
    "mismatches": [_serialize_mismatch(item) for item in mismatches],
    "summary": summary,
    "add_units": added_units,
  }
