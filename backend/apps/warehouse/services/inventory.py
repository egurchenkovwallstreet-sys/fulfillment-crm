"""Инвентаризация: фактический остаток на фулфилменте → CRM → WB FBS."""
from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from apps.integrations.models import AuditLog
from apps.integrations.marketplace import OZON, WB, normalize_marketplace
from apps.sellers.models import Seller, SellerWarehouse
from apps.warehouse.models import Product, ProductWarehouseStock, StockOperation
from apps.warehouse.services.cell_label import build_cell_label_data
from apps.warehouse.services.cells import first_free_cell, refresh_cell_occupied
from apps.warehouse.services.intake import IntakeError, _assign_cell
from apps.warehouse.services.marking_lookup import lookup_marking_for_barcode
from apps.warehouse.services.stock_transfer import even_split_quantity
from apps.warehouse.services.wb_stocks import (
  WBStockError,
  fetch_wb_stocks_for_warehouses,
  get_enabled_seller_warehouses,
  set_wb_stock_absolute,
)


@dataclass
class InventoryWarehouseLine:
  warehouse_id: int
  warehouse_name: str
  wb_warehouse_id: int
  sent_amount: int
  wb_actual: int
  difference: int


@dataclass
class InventoryResult:
  product: Product
  print_cell_label: bool
  cell_label: dict[str, str] | None
  fulfillment_quantity: int
  verified: bool
  warehouses: list[InventoryWarehouseLine]
  wb_total_sent: int
  wb_total_actual: int
  wb_total_difference: int


def _resolve_warehouses(seller: Seller, warehouse_ids: list[int]) -> list[SellerWarehouse]:
  if not warehouse_ids:
    raise IntakeError("Выберите хотя бы один FBS-склад")

  unique_ids = list(dict.fromkeys(warehouse_ids))
  warehouses = list(
    SellerWarehouse.objects.filter(
      seller=seller,
      pk__in=unique_ids,
    ).order_by("name", "id")
  )
  if len(warehouses) != len(unique_ids):
    raise IntakeError("Один или несколько складов не найдены")
  return warehouses


def _verify_inventory(
  seller: Seller,
  warehouses: list[SellerWarehouse],
  barcode: str,
  sent_by_warehouse: dict[int, int],
) -> list[InventoryWarehouseLine]:
  stock_map = fetch_wb_stocks_for_warehouses(seller, warehouses, [barcode])
  by_wh = (stock_map.get(barcode) or {}).get("by_warehouse") or {}

  lines: list[InventoryWarehouseLine] = []
  for warehouse in warehouses:
    sent = int(sent_by_warehouse.get(warehouse.id, 0))
    actual = int(by_wh.get(warehouse.id, 0))
    lines.append(
      InventoryWarehouseLine(
        warehouse_id=warehouse.id,
        warehouse_name=warehouse.name or f"Склад #{warehouse.wb_warehouse_id}",
        wb_warehouse_id=warehouse.wb_warehouse_id,
        sent_amount=sent,
        wb_actual=actual,
        difference=actual - sent,
      )
    )
  return lines


@transaction.atomic
def perform_inventory(
  *,
  seller: Seller,
  barcode: str,
  quantity: int,
  warehouse_ids: list[int],
  user,
  cell_mode: str = "auto",
  cell_id: int | None = None,
  name: str = "",
  marketplace: str = WB,
) -> InventoryResult:
  mp = normalize_marketplace(marketplace)
  barcode = barcode.strip()
  if not barcode:
    raise IntakeError("Баркод не может быть пустым")
  if quantity < 0:
    raise IntakeError("Количество не может быть отрицательным")

  warehouses = [] if mp == OZON else _resolve_warehouses(seller, warehouse_ids)
  targets = (
    even_split_quantity(quantity, len(warehouses))
    if len(warehouses) > 1
    else ([quantity] if warehouses else [])
  )
  sent_by_warehouse = {
    warehouse.id: target
    for warehouse, target in zip(warehouses, targets, strict=True)
  }

  product = (
    Product.objects.select_for_update()
    .filter(seller=seller, barcode=barcode, marketplace=mp)
    .select_related("cell", "seller")
    .first()
  )

  if product:
    product.quantity = quantity
    product.save(update_fields=["quantity", "updated_at"])
    is_new = False
  else:
    if quantity == 0:
      raise IntakeError("Новый баркод нельзя инвентаризировать с нулевым количеством")
    cell = _assign_cell(seller, cell_mode, cell_id, mp)
    marking = lookup_marking_for_barcode(seller, barcode) if mp == WB else None
    product = Product.objects.create(
      seller=seller,
      barcode=barcode,
      name=name.strip() or (marking.title if marking else ""),
      cell=cell,
      quantity=quantity,
      marketplace=mp,
      requires_marking=(marking.requires_marking if marking and marking.wb_found else False),
    )
    refresh_cell_occupied(cell)
    is_new = True

  if mp != OZON:
    for warehouse, target in zip(warehouses, targets, strict=True):
      try:
        set_wb_stock_absolute(seller, warehouse, barcode, target)
      except WBStockError as exc:
        raise IntakeError(str(exc)) from exc

      ProductWarehouseStock.objects.update_or_create(
        product=product,
        seller_warehouse=warehouse,
        defaults={"quantity": target},
      )

    selected_ids = {wh.id for wh in warehouses}
    for warehouse in get_enabled_seller_warehouses(seller):
      if warehouse.id in selected_ids:
        continue
      ProductWarehouseStock.objects.filter(
        product=product,
        seller_warehouse=warehouse,
      ).update(quantity=0)

  warehouse_labels = ", ".join(
    f"{wh.name or wh.wb_warehouse_id}={sent_by_warehouse[wh.id]}"
    for wh in warehouses
  )
  StockOperation.objects.create(
    product=product,
    operation_type=StockOperation.OperationType.ADJUSTMENT,
    quantity=quantity,
    performed_by=user,
    comment=(
      f"Инвентаризация Ozon: {quantity} шт."
      if mp == OZON
      else f"Инвентаризация: {quantity} шт. → WB ({warehouse_labels})"
    ),
  )

  if mp == OZON:
    lines = []
    wb_total_sent = quantity
    wb_total_actual = quantity
    verified = True
  else:
    lines = _verify_inventory(seller, warehouses, barcode, sent_by_warehouse)
    wb_total_sent = sum(line.sent_amount for line in lines)
    wb_total_actual = sum(line.wb_actual for line in lines)
    verified = all(line.difference == 0 for line in lines)

  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.OTHER,
    message=(
      f"Инвентаризация баркод {barcode}: {quantity} шт., "
      f"{'сверка OK' if verified else 'расхождение с WB'}"
    ),
    details={
      "barcode": barcode,
      "fulfillment_quantity": quantity,
      "verified": verified,
      "warehouse_ids": warehouse_ids,
      "sent_by_warehouse": sent_by_warehouse,
      "verification": [
        {
          "warehouse_id": line.warehouse_id,
          "warehouse_name": line.warehouse_name,
          "wb_warehouse_id": line.wb_warehouse_id,
          "sent_amount": line.sent_amount,
          "wb_actual": line.wb_actual,
          "difference": line.difference,
        }
        for line in lines
      ],
      "wb_total_sent": wb_total_sent,
      "wb_total_actual": wb_total_actual,
    },
  )

  cell_label = build_cell_label_data(product) if is_new else None
  return InventoryResult(
    product=product,
    print_cell_label=is_new,
    cell_label=cell_label,
    fulfillment_quantity=quantity,
    verified=verified,
    warehouses=lines,
    wb_total_sent=wb_total_sent,
    wb_total_actual=wb_total_actual,
    wb_total_difference=wb_total_actual - wb_total_sent,
  )
