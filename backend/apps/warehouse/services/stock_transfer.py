"""Перераспределение остатков между FBS-складами WB."""
from __future__ import annotations

from django.db import transaction

from apps.integrations.models import AuditLog
from apps.sellers.models import Seller
from apps.warehouse.models import Product, ProductWarehouseStock, StockOperation
from apps.warehouse.services.wb_stocks import (
  WBStockError,
  fetch_summed_wb_stocks,
  get_enabled_seller_warehouses,
  transfer_wb_stock_between_warehouses,
)


class StockTransferError(Exception):
  pass


def build_stock_overview(seller: Seller) -> dict:
  """Список товаров CRM с разбивкой остатков по FBS-складам WB."""
  products = list(
    Product.objects.filter(seller=seller)
    .select_related("cell")
    .order_by("cell__number")
  )
  if not products:
    return {"products": [], "warehouses": []}

  warehouses = get_enabled_seller_warehouses(seller)
  barcodes = [p.barcode for p in products]

  try:
    stock_map = fetch_summed_wb_stocks(seller, barcodes)
  except WBStockError as exc:
    raise StockTransferError(str(exc)) from exc

  wh_meta = [
    {"id": wh.id, "wb_warehouse_id": wh.wb_warehouse_id, "name": wh.name or f"Склад #{wh.wb_warehouse_id}"}
    for wh in warehouses
  ]

  rows = []
  for product in products:
    stock = stock_map.get(product.barcode, {"total": 0, "by_warehouse": {}})
    by_wh = []
    for wh in warehouses:
      qty = int((stock.get("by_warehouse") or {}).get(wh.id, 0))
      by_wh.append({"warehouse_id": wh.id, "quantity": qty})
      ProductWarehouseStock.objects.update_or_create(
        product=product,
        seller_warehouse=wh,
        defaults={"quantity": qty},
      )

    total = int(stock.get("total") or 0)
    if product.quantity != total:
      product.quantity = total
      product.save(update_fields=["quantity", "updated_at"])

    rows.append({
      "product_id": product.id,
      "barcode": product.barcode,
      "name": product.name,
      "cell_number": product.cell.number,
      "photo_url": product.photo_url,
      "wb_size": product.wb_size,
      "tech_size": product.tech_size,
      "crm_quantity": total,
      "wb_total": total,
      "by_warehouse": by_wh,
    })

  return {"products": rows, "warehouses": wh_meta}


@transaction.atomic
def perform_stock_transfer(
  seller: Seller,
  *,
  product_id: int,
  from_warehouse_id: int,
  to_warehouse_id: int,
  quantity: int,
  user=None,
) -> dict:
  try:
    product = Product.objects.select_related("cell").get(pk=product_id, seller=seller)
  except Product.DoesNotExist as exc:
    raise StockTransferError("Товар не найден") from exc

  try:
    result = transfer_wb_stock_between_warehouses(
      seller,
      barcode=product.barcode,
      from_warehouse_id=from_warehouse_id,
      to_warehouse_id=to_warehouse_id,
      quantity=quantity,
    )
  except WBStockError as exc:
    raise StockTransferError(str(exc)) from exc

  from_wh_id = result["from_warehouse"]["id"]
  to_wh_id = result["to_warehouse"]["id"]

  from_row, _ = ProductWarehouseStock.objects.get_or_create(
    product=product,
    seller_warehouse_id=from_wh_id,
    defaults={"quantity": 0},
  )
  to_row, _ = ProductWarehouseStock.objects.get_or_create(
    product=product,
    seller_warehouse_id=to_wh_id,
    defaults={"quantity": 0},
  )
  from_row.quantity = result["from_warehouse"]["new"]
  to_row.quantity = result["to_warehouse"]["new"]
  from_row.save(update_fields=["quantity", "updated_at"])
  to_row.save(update_fields=["quantity", "updated_at"])

  product.quantity = result["total"]
  product.save(update_fields=["quantity", "updated_at"])

  StockOperation.objects.create(
    product=product,
    operation_type=StockOperation.OperationType.ADJUSTMENT,
    quantity=0,
    performed_by=user,
    comment=(
      f"Перераспределение WB: {quantity} шт. "
      f"«{result['from_warehouse']['name']}» → «{result['to_warehouse']['name']}» "
      f"(сумма {result['total']} без изменений)"
    ),
  )

  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.INTAKE,
    message=f"Перераспределение остатков {product.barcode}: {quantity} шт.",
    details=result,
  )

  return {
    "success": True,
    "product": {
      "id": product.id,
      "barcode": product.barcode,
      "crm_quantity": product.quantity,
    },
    "transfer": result,
  }
