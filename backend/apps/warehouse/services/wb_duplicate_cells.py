"""Дубли ячеек: один chrtId WB — несколько Product в разных ячейках (баркод + джитины)."""
from __future__ import annotations

from collections import defaultdict

from django.db import transaction

from apps.integrations.marketplace import WB as MARKETPLACE_WB
from apps.integrations.models import AuditLog
from apps.sellers.models import Seller
from apps.warehouse.models import Cell, Product, ProductBarcodeAlias, StockOperation
from apps.warehouse.services.catalog_fetch import (
  CatalogError,
  build_seller_catalog_index,
  catalog_index_get,
  normalize_barcode,
)
from apps.warehouse.services.cells import refresh_cell_occupied
from apps.warehouse.services.product_lookup import ensure_barcode_alias, sync_product_wb_barcodes


class DuplicateCellsError(Exception):
  pass


def _chrt_id_for_product(product: Product, catalog_index: dict | None) -> int | None:
  chrt_id = product.wb_chrt_id
  if catalog_index:
    item = catalog_index_get(catalog_index, product.barcode)
    if item and item.wb_chrt_id:
      chrt_id = int(item.wb_chrt_id)
  if chrt_id:
    return int(chrt_id)
  return None


def find_wb_duplicate_cell_groups(
  seller: Seller,
  *,
  catalog_index: dict | None = None,
) -> list[dict]:
  """
  Группы товаров с одним chrtId WB в разных ячейках.
  Каждая группа: chrt_id, products [{id, cell_number, barcode, quantity}], cell_numbers.
  """
  index = catalog_index
  if index is None:
    try:
      index = build_seller_catalog_index(seller)
    except CatalogError:
      index = {}

  products = list(
    Product.objects.filter(seller=seller, marketplace=MARKETPLACE_WB)
    .select_related("cell")
    .order_by("cell__number", "id")
  )
  by_chrt: dict[int, list[Product]] = defaultdict(list)
  for product in products:
    chrt_id = _chrt_id_for_product(product, index)
    if chrt_id:
      by_chrt[chrt_id].append(product)

  groups: list[dict] = []
  for chrt_id, plist in sorted(by_chrt.items(), key=lambda x: x[0]):
    cell_ids = {p.cell_id for p in plist if p.cell_id}
    if len(plist) < 2 or len(cell_ids) < 2:
      continue
    entries = [
      {
        "id": p.id,
        "cell_number": str(p.cell.number) if p.cell_id else "—",
        "barcode": p.barcode,
        "quantity": int(p.quantity or 0),
      }
      for p in plist
    ]
    cell_numbers = sorted({e["cell_number"] for e in entries if e["cell_number"] != "—"})
    groups.append({
      "chrt_id": chrt_id,
      "cell_numbers": cell_numbers,
      "products": entries,
    })
  return groups


def duplicate_meta_by_product_id(
  seller: Seller,
  *,
  catalog_index: dict | None = None,
) -> dict[int, dict]:
  """product_id → duplicate_cell_numbers, duplicate_product_ids, chrt_id."""
  result: dict[int, dict] = {}
  for group in find_wb_duplicate_cell_groups(seller, catalog_index=catalog_index):
    product_ids = [p["id"] for p in group["products"]]
    cell_numbers = group["cell_numbers"]
    chrt_id = group["chrt_id"]
    for entry in group["products"]:
      pid = entry["id"]
      others_cells = [n for n in cell_numbers if n != entry["cell_number"]]
      others_ids = [i for i in product_ids if i != pid]
      result[pid] = {
        "has_duplicate_cells": True,
        "duplicate_chrt_id": chrt_id,
        "duplicate_cell_numbers": others_cells,
        "duplicate_product_ids": others_ids,
      }
  return result


def _products_in_chrt_group(
  seller: Seller,
  chrt_id: int,
  *,
  catalog_index: dict | None,
) -> list[Product]:
  products = list(
    Product.objects.filter(seller=seller, marketplace=MARKETPLACE_WB).select_related("cell")
  )
  return [p for p in products if _chrt_id_for_product(p, catalog_index) == chrt_id]


def _group_products_for_target(
  seller: Seller,
  target: Product,
  *,
  catalog_index: dict | None,
) -> list[Product]:
  chrt_id = _chrt_id_for_product(target, catalog_index)
  if not chrt_id:
    raise DuplicateCellsError("Не удалось определить размер WB (chrtId) для объединения")
  products = _products_in_chrt_group(seller, chrt_id, catalog_index=catalog_index)

  cell_ids = {p.cell_id for p in products if p.cell_id}
  if len(products) < 2 or len(cell_ids) < 2:
    raise DuplicateCellsError("Дублирующих ячеек для этого товара не найдено")
  if target.id not in {p.id for p in products}:
    raise DuplicateCellsError("Товар не входит в группу дублей")
  return products


@transaction.atomic
def merge_wb_duplicate_products(
  seller: Seller,
  *,
  target_product_id: int,
  user,
  catalog_index: dict | None = None,
) -> Product:
  """Объединить все Product одного chrtId в target; остальные удалить, ячейки освободить."""
  from apps.orders.models import Order, PickListItem

  try:
    target = Product.objects.select_for_update().select_related("cell", "seller").get(
      pk=target_product_id,
      seller=seller,
      marketplace=MARKETPLACE_WB,
    )
  except Product.DoesNotExist as exc:
    raise DuplicateCellsError("Целевой товар не найден") from exc

  index = catalog_index
  if index is None:
    try:
      index = build_seller_catalog_index(seller)
    except CatalogError:
      index = {}

  group = _group_products_for_target(seller, target, catalog_index=index)
  sources = [p for p in group if p.id != target.id]
  if not sources:
    raise DuplicateCellsError("Нечего объединять")

  merged_barcodes: list[str] = []
  merged_cells: list[str] = []
  total_added_qty = 0

  for source in sources:
    source = Product.objects.select_for_update().select_related("cell").get(pk=source.pk)
    merged_barcodes.append(source.barcode)
    if source.cell_id:
      merged_cells.append(str(source.cell.number))
    total_added_qty += int(source.quantity or 0)

    src_barcode = normalize_barcode(source.barcode)
    if src_barcode and src_barcode != normalize_barcode(target.barcode):
      ensure_barcode_alias(target, src_barcode)

    for alias in ProductBarcodeAlias.objects.filter(product=source):
      code = normalize_barcode(alias.barcode)
      if code:
        ensure_barcode_alias(target, code)

    Order.objects.filter(product=source).update(product=target)
    PickListItem.objects.filter(product=source).update(product=target)

    old_cell = source.cell
    source.delete()
    if old_cell_id := getattr(old_cell, "id", None):
      cell_obj = Cell.objects.filter(pk=old_cell_id).first()
      if cell_obj and not cell_obj.products.exists():
        cell_obj.delete()
      elif cell_obj:
        refresh_cell_occupied(cell_obj)

  if total_added_qty:
    target.quantity = int(target.quantity or 0) + total_added_qty
    target.save(update_fields=["quantity", "updated_at"])

  sync_product_wb_barcodes(seller, target, catalog_index=index)

  chrt_id = _chrt_id_for_product(target, index)
  if chrt_id and target.wb_chrt_id != chrt_id:
    target.wb_chrt_id = chrt_id
    target.save(update_fields=["wb_chrt_id", "updated_at"])

  refresh_cell_occupied(target.cell)

  StockOperation.objects.create(
    product=target,
    operation_type=StockOperation.OperationType.ADJUSTMENT,
    quantity=total_added_qty,
    performed_by=user,
    comment=(
      f"Объединение дублей chrt {chrt_id}: +{total_added_qty} шт., "
      f"удалены ячейки {', '.join(merged_cells)}"
    ),
  )

  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.INTAKE,
    message=(
      f"Объединены дубли WB в яч. №{target.cell.number}: "
      f"{', '.join(merged_barcodes)} → {target.barcode}"
    ),
    details={
      "target_product_id": target.id,
      "merged_product_barcodes": merged_barcodes,
      "merged_cell_numbers": merged_cells,
      "quantity_added": total_added_qty,
      "chrt_id": chrt_id,
    },
  )

  target.refresh_from_db()
  return target
