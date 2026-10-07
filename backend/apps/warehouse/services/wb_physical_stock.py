"""Выставление остатка в ЛК WB от факта на полке: CRM как ввёл менеджер, WB − заказы (live API)."""
from __future__ import annotations

from apps.sellers.models import Seller, SellerWarehouse
from apps.warehouse.models import Product
from apps.warehouse.services.live_wb_orders import (
  LiveWbOrdersError,
  count_live_open_orders_for_barcode_on_warehouse,
  count_live_open_orders_for_warehouses,
  live_open_orders_error_as_wb_stock,
)
from apps.warehouse.services.stock_balance import compute_wb_amount_from_crm
from apps.warehouse.services.wb_stocks import WBStockError


def live_reserve_for_wb_write(
  seller: Seller,
  barcode: str,
  warehouses: list[SellerWarehouse],
) -> tuple[int, int, int]:
  if not warehouses:
    return 0, 0, 0
  if len(warehouses) == 1:
    return count_live_open_orders_for_barcode_on_warehouse(seller, barcode, warehouses[0])
  return count_live_open_orders_for_warehouses(seller, barcode, warehouses)


def push_wb_for_manager_physical_count(
  *,
  seller: Seller,
  product: Product,
  warehouse: SellerWarehouse,
  barcode: str,
  crm_quantity: int,
  stock_mode_label: str,
) -> tuple[dict, bool, int, bool, int, int, int, int]:
  """
  CRM уже = crm_quantity. В ЛК WB: crm − (новые + на сборке) по этому складу, заказы — live API.
  Возвращает (wb_sync, verified, wb_target, restock, wb_before, wb_actual, new_n, pick_n).
  """
  try:
    reserved_new, reserved_picking, reserved_total = count_live_open_orders_for_barcode_on_warehouse(
      seller,
      barcode,
      warehouse,
    )
  except LiveWbOrdersError as exc:
    raise live_open_orders_error_as_wb_stock(exc) from exc

  from apps.warehouse.services.intake import _write_wb_balance_for_intake

  wb_sync, verified, wb_target, restock_required, wb_before, wb_actual = _write_wb_balance_for_intake(
    seller=seller,
    product=product,
    warehouse=warehouse,
    barcode=barcode,
    crm_quantity=crm_quantity,
    reserved_new_orders=reserved_total,
  )
  wb_sync["mode"] = stock_mode_label
  wb_sync["reserved_new_orders"] = reserved_new
  wb_sync["reserved_picking_orders"] = reserved_picking
  wb_sync["reserved_open_orders"] = reserved_total
  return (
    wb_sync,
    verified,
    wb_target,
    restock_required,
    wb_before,
    wb_actual,
    reserved_new,
    reserved_picking,
  )


def wb_target_for_manager_physical_count(
  seller: Seller,
  barcode: str,
  crm_quantity: int,
  warehouses: list[SellerWarehouse],
) -> tuple[int, bool, int, int, int]:
  """(wb_target, restock, new, pick, total_reserve) — только расчёт, без push."""
  try:
    reserved_new, reserved_picking, reserved_total = live_reserve_for_wb_write(
      seller,
      barcode,
      warehouses,
    )
  except LiveWbOrdersError as exc:
    raise live_open_orders_error_as_wb_stock(exc) from exc
  wb_target, restock_required = compute_wb_amount_from_crm(crm_quantity, reserved_total)
  return wb_target, restock_required, reserved_new, reserved_picking, reserved_total
