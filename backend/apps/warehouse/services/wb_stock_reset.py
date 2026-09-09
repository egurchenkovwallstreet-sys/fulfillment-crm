"""Массовое обнуление остатков WB и CRM по выбранным FBS-складам."""
from __future__ import annotations

from django.db import transaction
from django.db.models import Sum

from apps.integrations.marketplace import WB as MARKETPLACE_WB
from apps.integrations.models import AuditLog
from apps.sellers.models import Seller, SellerWarehouse
from apps.warehouse.models import Product, ProductWarehouseStock
from apps.warehouse.services.catalog_fetch import CatalogError, fetch_seller_catalog_items
from apps.warehouse.services.wb_stocks import (
  WBStockError,
  fetch_wb_stocks_for_warehouses,
  set_wb_stocks_absolute_batch,
)


class WBStockResetError(Exception):
  pass


def _collect_barcodes(seller: Seller) -> list[str]:
  barcodes: list[str] = []
  seen: set[str] = set()

  def add(values: list[str]) -> None:
    for value in values:
      code = str(value or "").strip()
      if not code or code in seen:
        continue
      seen.add(code)
      barcodes.append(code)

  try:
    add([item.barcode for item in fetch_seller_catalog_items(seller)])
  except CatalogError:
    pass

  add(
    list(
      Product.objects.filter(seller=seller, marketplace=MARKETPLACE_WB).values_list(
        "barcode",
        flat=True,
      )
    )
  )
  return barcodes


def _recalculate_product_totals(product_ids: set[int]) -> int:
  updated = 0
  for product in Product.objects.filter(pk__in=product_ids):
    total = (
      ProductWarehouseStock.objects.filter(product=product).aggregate(s=Sum("quantity")).get("s")
      or 0
    )
    total = max(0, int(total))
    if product.quantity != total:
      product.quantity = total
      product.save(update_fields=["quantity", "updated_at"])
      updated += 1
  return updated


def reset_wb_and_crm_stocks(
  seller: Seller,
  warehouse_ids: list[int],
  *,
  user=None,
) -> dict:
  """
  Обнулить в ЛК WB все баркоды с остатком > 0 на выбранных складах
  и сбросить ProductWarehouseStock + Product.quantity в CRM.
  """
  if not warehouse_ids:
    raise WBStockResetError("Выберите хотя бы один FBS-склад")

  warehouses = list(
    SellerWarehouse.objects.filter(
      seller=seller,
      pk__in=warehouse_ids,
      is_enabled=True,
    ).order_by("name", "id")
  )
  if not warehouses:
    raise WBStockResetError("Нет выбранных обслуживаемых FBS-складов")

  if not seller.wb_api_token_encrypted:
    raise WBStockResetError(f"У селлера «{seller.company_name}» не задан токен WB")

  barcodes = _collect_barcodes(seller)
  if not barcodes:
    raise WBStockResetError("Не найдены баркоды каталога WB — загрузите каталог или товары в CRM")

  warehouse_results: list[dict] = []
  total_wb_zeroed = 0
  total_wb_units = 0

  for warehouse in warehouses:
    try:
      stock_map = fetch_wb_stocks_for_warehouses(seller, [warehouse], barcodes)
    except WBStockError as exc:
      raise WBStockResetError(str(exc)) from exc

    to_zero: list[tuple[str, int]] = []
    units_before = 0
    for barcode in barcodes:
      by_wh = (stock_map.get(barcode) or {}).get("by_warehouse") or {}
      qty = int(by_wh.get(warehouse.id) or 0)
      if qty > 0:
        to_zero.append((barcode, 0))
        units_before += qty

    pushed = 0
    if to_zero:
      try:
        pushed = set_wb_stocks_absolute_batch(seller, warehouse, to_zero)
      except WBStockError as exc:
        raise WBStockResetError(
          f"Склад «{warehouse.name or warehouse.wb_warehouse_id}»: {exc}"
        ) from exc

    total_wb_zeroed += pushed
    total_wb_units += units_before
    warehouse_results.append({
      "warehouse_id": warehouse.id,
      "warehouse_name": warehouse.name,
      "wb_warehouse_id": warehouse.wb_warehouse_id,
      "wb_barcodes_zeroed": pushed,
      "wb_units_before": units_before,
    })

  warehouse_pks = [warehouse.id for warehouse in warehouses]
  warehouse_names = ", ".join(
    warehouse.name or f"#{warehouse.wb_warehouse_id}" for warehouse in warehouses
  )
  affected_product_ids = set(
    ProductWarehouseStock.objects.filter(
      seller_warehouse_id__in=warehouse_pks,
    ).values_list("product_id", flat=True)
  )

  with transaction.atomic():
    crm_rows = ProductWarehouseStock.objects.filter(
      seller_warehouse_id__in=warehouse_pks,
      quantity__gt=0,
    ).update(quantity=0)
    products_recalculated = _recalculate_product_totals(affected_product_ids)

    audit_message = (
      f"Обнулено на WB: {total_wb_zeroed} баркодов ({total_wb_units} шт.) "
      f"на складах: {warehouse_names}. "
      f"CRM: сброшено {crm_rows} строк остатков."
    )
    AuditLog.objects.create(
      seller=seller,
      user=user,
      action_type=AuditLog.ActionType.OTHER,
      message=audit_message,
      details={
        "action": "reset_wb_crm_stocks",
        "warehouse_ids": warehouse_pks,
        "wb_barcodes_zeroed": total_wb_zeroed,
        "wb_units_before": total_wb_units,
        "crm_rows_zeroed": crm_rows,
        "products_recalculated": products_recalculated,
      },
    )

  message = audit_message

  return {
    "success": True,
    "message": message,
    "warehouses": warehouse_results,
    "wb_barcodes_zeroed": total_wb_zeroed,
    "wb_units_before": total_wb_units,
    "crm_rows_zeroed": crm_rows,
    "products_recalculated": products_recalculated,
  }
