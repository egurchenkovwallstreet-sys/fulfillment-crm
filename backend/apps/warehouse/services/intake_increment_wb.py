"""Приёмка +N и Excel increment: живой остаток WB +N, CRM = WB + заказы (новые + сборка)."""
from __future__ import annotations

from dataclasses import dataclass

from apps.sellers.models import Seller, SellerWarehouse
from apps.warehouse.models import Product, ProductWarehouseStock
from apps.warehouse.services.live_wb_orders import (
  LiveWbOrdersError,
  count_live_open_orders_for_barcode_on_warehouse,
  live_open_orders_error_as_wb_stock,
)
from apps.warehouse.services.wb_stocks import (
  WBStockError,
  fetch_wb_stock_for_barcode,
  push_wb_stock_absolute,
)


@dataclass
class WbIncrementStockResult:
  wb_quantity_before: int
  wb_quantity_target: int
  wb_quantity_actual: int | None
  crm_quantity_after: int
  reserved_new_orders: int
  reserved_picking_orders: int
  verified: bool
  restock_required: bool
  wb_sync: dict


def apply_wb_increment_stock(
  *,
  seller: Seller,
  warehouse: SellerWarehouse,
  product: Product,
  barcode: str,
  add_quantity: int,
  stock_mode_label: str,
) -> WbIncrementStockResult:
  add_quantity = max(0, int(add_quantity))
  if add_quantity <= 0:
    raise WBStockError("Количество должно быть больше 0")

  try:
    wb_before = fetch_wb_stock_for_barcode(seller, warehouse, barcode, product=product)
  except WBStockError:
    raise

  wb_target = wb_before + add_quantity

  try:
    reserved_new, reserved_picking, reserved_total = count_live_open_orders_for_barcode_on_warehouse(
      seller,
      barcode,
      warehouse,
    )
  except LiveWbOrdersError as exc:
    raise live_open_orders_error_as_wb_stock(exc) from exc

  crm_after = wb_target + reserved_total

  try:
    push_result = push_wb_stock_absolute(
      seller,
      warehouse,
      barcode,
      wb_target,
      product=product,
    )
  except WBStockError:
    raise

  ProductWarehouseStock.objects.update_or_create(
    product=product,
    seller_warehouse=warehouse,
    defaults={"quantity": wb_target},
  )

  product.quantity = crm_after
  product.save(update_fields=["quantity", "updated_at"])

  wb_actual = fetch_wb_stock_for_barcode(seller, warehouse, barcode, product=product)
  verified = wb_actual == wb_target

  wb_sync = {
    **push_result,
    "mode": stock_mode_label,
    "target_wb_amount": wb_target,
    "actual_wb_amount": wb_actual,
    "verified": verified,
    "wb_quantity_before": wb_before,
    "add_quantity": add_quantity,
    "reserved_new_orders": reserved_new,
    "reserved_picking_orders": reserved_picking,
    "reserved_open_orders": reserved_total,
    "crm_quantity": crm_after,
  }

  return WbIncrementStockResult(
    wb_quantity_before=wb_before,
    wb_quantity_target=wb_target,
    wb_quantity_actual=wb_actual,
    crm_quantity_after=crm_after,
    reserved_new_orders=reserved_new,
    reserved_picking_orders=reserved_picking,
    verified=verified,
    restock_required=False,
    wb_sync=wb_sync,
  )
