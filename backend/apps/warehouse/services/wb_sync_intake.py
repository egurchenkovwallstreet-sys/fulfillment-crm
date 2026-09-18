"""Сверка с WB при приёмке: автоматически или по сканированию."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from django.core.cache import cache
from django.db import transaction

from apps.integrations.marketplace import WB
from apps.integrations.models import AuditLog
from apps.sellers.models import Seller
from apps.warehouse.models import Cell, Product, StockOperation
from apps.warehouse.services.catalog_fetch import (
  CatalogBarcodeItem,
  CatalogError,
  fetch_seller_catalog_items,
)
from apps.warehouse.services.cell_label import build_cell_label_data
from apps.warehouse.services.cells import _next_cell_number, create_cell_with_next_number, refresh_cell_occupied
from apps.warehouse.services.product_catalog import (
  catalog_item_to_create_kwargs,
  try_enrich_product_from_catalog,
)
from apps.warehouse.services.wb_stocks import WBStockError, fetch_wb_stocks_for_warehouses, get_seller_warehouse


class WbSyncIntakeError(Exception):
  pass


WB_SYNC_PREVIEW_CACHE_VERSION = "v1"
WB_SYNC_PREVIEW_CACHE_TTL = 900


@dataclass
class WbSyncPreviewItem:
  barcode: str
  title: str
  tech_size: str
  wb_stock: int
  cell_number: str
  already_in_crm: bool
  requires_marking: bool
  wb_size: str = ""
  vendor_code: str = ""
  wb_nm_id: int | None = None
  photo_url: str = ""
  color_label: str = ""
  product_id: int | None = None
  crm_quantity: int | None = None


@dataclass
class WbSyncPreviewResult:
  warehouse_id: int
  warehouse_name: str
  items: list[WbSyncPreviewItem] = field(default_factory=list)


@dataclass
class WbSyncApplyResult:
  created: int = 0
  updated: int = 0
  skipped: int = 0
  products: list[Product] = field(default_factory=list)
  cell_labels: list[dict] = field(default_factory=list)


def _wb_sync_preview_cache_key(seller_id: int, warehouse_pk: int) -> str:
  return f"wb_sync_preview:{WB_SYNC_PREVIEW_CACHE_VERSION}:{seller_id}:{warehouse_pk}"


def _warehouse_stock(stock_row: dict, warehouse_pk: int) -> int:
  by_wh = stock_row.get("by_warehouse") or {}
  try:
    return max(0, int(by_wh.get(warehouse_pk) or by_wh.get(str(warehouse_pk)) or 0))
  except (TypeError, ValueError):
    return max(0, int(stock_row.get("total") or 0))


def _preview_item_from_catalog(
  catalog_item: CatalogBarcodeItem,
  *,
  wb_stock: int,
  product: Product | None,
  cell_number: str,
) -> WbSyncPreviewItem:
  return WbSyncPreviewItem(
    barcode=catalog_item.barcode,
    title=catalog_item.title,
    tech_size=catalog_item.tech_size,
    wb_size=catalog_item.wb_size,
    vendor_code=catalog_item.vendor_code,
    wb_nm_id=catalog_item.wb_nm_id or None,
    photo_url=catalog_item.photo_url,
    color_label=catalog_item.color_label,
    wb_stock=wb_stock,
    cell_number=cell_number,
    already_in_crm=product is not None,
    requires_marking=catalog_item.requires_marking,
    product_id=product.id if product else None,
    crm_quantity=product.quantity if product else None,
  )


def _load_wb_sync_items(seller: Seller, warehouse_pk: int) -> list[WbSyncPreviewItem]:
  """
  Лёгкая загрузка: кэш каталога WB + один запрос остатков по складу.
  Без build_onboarding_preview (лишняя группировка и двойная работа).
  """
  warehouse = get_seller_warehouse(seller, warehouse_pk)
  try:
    catalog_items = fetch_seller_catalog_items(seller)
  except CatalogError as exc:
    raise WbSyncIntakeError(str(exc)) from exc

  if not catalog_items:
    raise WbSyncIntakeError("На WB не найдено карточек с баркодами")

  catalog_by_barcode = {item.barcode: item for item in catalog_items}
  existing = {
    p.barcode: p
    for p in Product.objects.filter(seller=seller, marketplace=WB).select_related("cell")
  }

  try:
    stock_map = fetch_wb_stocks_for_warehouses(
      seller,
      [warehouse],
      list(catalog_by_barcode.keys()),
    )
  except WBStockError as exc:
    raise WbSyncIntakeError(str(exc)) from exc

  preview_items: list[WbSyncPreviewItem] = []
  new_items: list[WbSyncPreviewItem] = []
  for barcode, catalog_item in catalog_by_barcode.items():
    stock_row = stock_map.get(barcode) or {}
    wb_stock = _warehouse_stock(stock_row, warehouse.id)
    if wb_stock < 1:
      continue
    product = existing.get(barcode)
    preview = _preview_item_from_catalog(
      catalog_item,
      wb_stock=wb_stock,
      product=product,
      cell_number=product.cell.number if product and product.cell_id else "",
    )
    if not product:
      new_items.append(preview)
    preview_items.append(preview)

  if new_items:
    start_from = int(_next_cell_number(seller, WB))
    for offset, preview in enumerate(new_items):
      preview.cell_number = str(start_from + offset)

  return preview_items


def _store_preview_cache(seller_id: int, warehouse_pk: int, items: list[WbSyncPreviewItem]) -> None:
  cache.set(
    _wb_sync_preview_cache_key(seller_id, warehouse_pk),
    [asdict(item) for item in items],
    WB_SYNC_PREVIEW_CACHE_TTL,
  )


def _load_preview_cache(seller_id: int, warehouse_pk: int) -> list[WbSyncPreviewItem] | None:
  cached = cache.get(_wb_sync_preview_cache_key(seller_id, warehouse_pk))
  if not isinstance(cached, list) or not cached:
    return None
  items: list[WbSyncPreviewItem] = []
  for row in cached:
    if isinstance(row, dict):
      items.append(WbSyncPreviewItem(**row))
  return items or None


def preview_wb_sync_intake(seller: Seller, warehouse_pk: int) -> WbSyncPreviewResult:
  warehouse = get_seller_warehouse(seller, warehouse_pk)
  items = _load_wb_sync_items(seller, warehouse_pk)

  if not items:
    raise WbSyncIntakeError(
      f"На складе «{warehouse.name or warehouse.wb_warehouse_id}» нет остатков в ЛК WB"
    )

  _store_preview_cache(seller.id, warehouse_pk, items)
  return WbSyncPreviewResult(
    warehouse_id=warehouse.id,
    warehouse_name=warehouse.name or str(warehouse.wb_warehouse_id),
    items=items,
  )


def serialize_preview(result: WbSyncPreviewResult) -> dict:
  return {
    "warehouse_id": result.warehouse_id,
    "warehouse_name": result.warehouse_name,
    "items": [
      {
        "barcode": item.barcode,
        "title": item.title,
        "tech_size": item.tech_size,
        "wb_stock": item.wb_stock,
        "cell_number": item.cell_number,
        "already_in_crm": item.already_in_crm,
        "requires_marking": item.requires_marking,
        "product_id": item.product_id,
        "crm_quantity": item.crm_quantity,
      }
      for item in result.items
    ],
  }


@transaction.atomic
def apply_wb_sync_auto(
  seller: Seller,
  warehouse_pk: int,
  *,
  barcodes: list[str] | None = None,
  user=None,
) -> WbSyncApplyResult:
  warehouse = get_seller_warehouse(seller, warehouse_pk)
  cached_items = _load_preview_cache(seller.id, warehouse_pk)
  if cached_items is None:
    cached_items = _load_wb_sync_items(seller, warehouse_pk)

  selected = {b.strip() for b in (barcodes or []) if b and b.strip()}
  apply_all = not selected

  outcome = WbSyncApplyResult()
  for item in cached_items:
    if not apply_all and item.barcode not in selected:
      outcome.skipped += 1
      continue

    product = Product.objects.filter(
      seller=seller,
      marketplace=WB,
      barcode=item.barcode,
    ).select_related("cell", "seller").first()

    if product:
      product.quantity = item.wb_stock
      product.save(update_fields=["quantity", "updated_at"])
      try_enrich_product_from_catalog(product, seller)
      StockOperation.objects.create(
        product=product,
        operation_type=StockOperation.OperationType.ADJUSTMENT,
        quantity=item.wb_stock,
        performed_by=user,
        comment=(
          f"Сверка с WB (авто), склад {warehouse.name or warehouse.wb_warehouse_id}: "
          f"остаток CRM = {item.wb_stock} шт."
        ),
      )
      outcome.updated += 1
      outcome.products.append(product)
      continue

    cell_number = item.cell_number.strip()
    if cell_number:
      cell, _ = Cell.objects.get_or_create(
        seller=seller,
        marketplace=WB,
        number=cell_number,
        defaults={"is_occupied": False},
      )
    else:
      cell = create_cell_with_next_number(seller, WB)

    catalog_item = CatalogBarcodeItem(
      barcode=item.barcode,
      wb_nm_id=int(item.wb_nm_id or 0),
      vendor_code=item.vendor_code,
      title=item.title,
      tech_size=item.tech_size,
      wb_size=item.wb_size,
      photo_url=item.photo_url,
      requires_marking=item.requires_marking,
      color_label=item.color_label,
    )
    product = Product.objects.create(
      seller=seller,
      marketplace=WB,
      barcode=item.barcode,
      cell=cell,
      quantity=item.wb_stock,
      **catalog_item_to_create_kwargs(catalog_item),
    )
    refresh_cell_occupied(cell)
    StockOperation.objects.create(
      product=product,
      operation_type=StockOperation.OperationType.ADJUSTMENT,
      quantity=item.wb_stock,
      performed_by=user,
      comment=(
        f"Сверка с WB (авто), склад {warehouse.name or warehouse.wb_warehouse_id}: "
        f"создан товар, остаток CRM = {item.wb_stock} шт."
      ),
    )
    outcome.created += 1
    outcome.products.append(product)
    outcome.cell_labels.append(build_cell_label_data(product))

  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.INTAKE,
    message=(
      f"Сверка с WB (авто): создано {outcome.created}, обновлено {outcome.updated}, "
      f"склад {warehouse.name or warehouse.wb_warehouse_id}"
    ),
    details={
      "warehouse_id": warehouse.id,
      "created": outcome.created,
      "updated": outcome.updated,
      "skipped": outcome.skipped,
    },
  )
  cache.delete(_wb_sync_preview_cache_key(seller.id, warehouse_pk))
  return outcome
