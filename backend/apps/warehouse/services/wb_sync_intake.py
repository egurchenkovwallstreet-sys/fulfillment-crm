"""Сверка с WB при приёмке: автоматически или по сканированию."""
from __future__ import annotations

from dataclasses import dataclass, field

from django.db import transaction

from apps.integrations.marketplace import WB
from apps.integrations.models import AuditLog
from apps.sellers.models import Seller
from apps.warehouse.models import Cell, Product, StockOperation
from apps.warehouse.services.catalog_fetch import (
  CATALOG_MODE_WITH_STOCK,
  CatalogError,
  build_onboarding_preview,
)
from apps.warehouse.services.cell_label import build_cell_label_data
from apps.warehouse.services.cells import create_cell_with_next_number, refresh_cell_occupied
from apps.warehouse.services.wb_stocks import WBStockError, get_seller_warehouse


class WbSyncIntakeError(Exception):
  pass


@dataclass
class WbSyncPreviewItem:
  barcode: str
  title: str
  tech_size: str
  wb_stock: int
  cell_number: str
  already_in_crm: bool
  requires_marking: bool
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


def _warehouse_stock(item: dict, warehouse_pk: int) -> int:
  by_wh = item.get("wb_stock_by_warehouse") or {}
  for key, qty in by_wh.items():
    try:
      if int(key) == warehouse_pk:
        return max(0, int(qty))
    except (TypeError, ValueError):
      continue
  return max(0, int(item.get("wb_stock_total") or 0))


def preview_wb_sync_intake(seller: Seller, warehouse_pk: int) -> WbSyncPreviewResult:
  warehouse = get_seller_warehouse(seller, warehouse_pk)
  try:
    preview = build_onboarding_preview(
      seller,
      catalog_mode=CATALOG_MODE_WITH_STOCK,
      warehouse_ids=[warehouse.id],
    )
  except CatalogError as exc:
    raise WbSyncIntakeError(str(exc)) from exc

  existing = {
    p.barcode: p
    for p in Product.objects.filter(seller=seller, marketplace=WB).select_related("cell")
  }

  items: list[WbSyncPreviewItem] = []
  for row in preview.get("items") or []:
    wb_stock = _warehouse_stock(row, warehouse.id)
    if wb_stock < 1:
      continue
    barcode = str(row.get("barcode") or "").strip()
    if not barcode:
      continue
    product = existing.get(barcode)
    items.append(
      WbSyncPreviewItem(
        barcode=barcode,
        title=str(row.get("title") or ""),
        tech_size=str(row.get("tech_size") or row.get("size_label") or ""),
        wb_stock=wb_stock,
        cell_number=str(row.get("cell_number") or ""),
        already_in_crm=bool(row.get("already_in_crm")),
        requires_marking=bool(row.get("requires_marking")),
        product_id=product.id if product else None,
        crm_quantity=product.quantity if product else None,
      )
    )

  if not items:
    raise WbSyncIntakeError(
      f"На складе «{warehouse.name or warehouse.wb_warehouse_id}» нет остатков в ЛК WB"
    )

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
  preview = preview_wb_sync_intake(seller, warehouse_pk)
  warehouse = get_seller_warehouse(seller, warehouse_pk)
  selected = {b.strip() for b in (barcodes or []) if b and b.strip()}
  apply_all = not selected

  outcome = WbSyncApplyResult()
  for item in preview.items:
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

    product = Product.objects.create(
      seller=seller,
      marketplace=WB,
      barcode=item.barcode,
      name=item.title,
      cell=cell,
      quantity=item.wb_stock,
      requires_marking=item.requires_marking,
      tech_size=item.tech_size,
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
  return outcome
