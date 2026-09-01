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
  set_wb_stock_absolute,
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


def even_split_quantity(total: int, parts: int) -> list[int]:
  """Разбить total на parts целых частей; сумма частей = total."""
  if parts <= 0:
    return []
  total = max(0, int(total))
  base = total // parts
  remainder = total % parts
  return [base + (1 if index < remainder else 0) for index in range(parts)]


def distribute_product_stock_evenly(
  seller: Seller,
  product: Product,
  *,
  warehouses: list | None = None,
  user=None,
) -> dict:
  """Равномерно распределить остаток баркода по включённым FBS-складам WB."""
  warehouses = warehouses or get_enabled_seller_warehouses(seller)
  if len(warehouses) < 2:
    raise StockTransferError("Нужно минимум 2 включённых FBS-склада для распределения")

  stock_map = fetch_summed_wb_stocks(seller, [product.barcode])
  data = stock_map.get(product.barcode, {"total": 0, "by_warehouse": {}})
  total = int(data.get("total") or 0)
  if total <= 0:
    return {
      "skipped": True,
      "reason": "zero_total",
      "product_id": product.id,
      "barcode": product.barcode,
      "total": 0,
    }

  by_wh = {int(key): int(value) for key, value in (data.get("by_warehouse") or {}).items()}
  targets = even_split_quantity(total, len(warehouses))
  if all(by_wh.get(wh.id, 0) == target for wh, target in zip(warehouses, targets, strict=True)):
    return {
      "skipped": True,
      "reason": "already_even",
      "product_id": product.id,
      "barcode": product.barcode,
      "total": total,
      "by_warehouse": [
        {"warehouse_id": wh.id, "quantity": by_wh.get(wh.id, 0)}
        for wh in warehouses
      ],
    }

  warehouse_results = []
  for wh, target in zip(warehouses, targets, strict=True):
    current = by_wh.get(wh.id, 0)
    if current != target:
      try:
        set_wb_stock_absolute(seller, wh, product.barcode, target)
      except WBStockError as exc:
        raise StockTransferError(str(exc)) from exc
    pws, _ = ProductWarehouseStock.objects.update_or_create(
      product=product,
      seller_warehouse=wh,
      defaults={"quantity": target},
    )
    warehouse_results.append({
      "warehouse_id": wh.id,
      "name": wh.name,
      "previous": current,
      "new": target,
    })

  product.quantity = total
  product.save(update_fields=["quantity", "updated_at"])

  StockOperation.objects.create(
    product=product,
    operation_type=StockOperation.OperationType.ADJUSTMENT,
    quantity=0,
    performed_by=user,
    comment=(
      f"Равномерное распределение WB: {total} шт. на {len(warehouses)} складов "
      f"({', '.join(str(row['new']) for row in warehouse_results)})"
    ),
  )

  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.INTAKE,
    message=f"Равномерное распределение {product.barcode}: {total} шт.",
    details={"total": total, "warehouses": warehouse_results},
  )

  return {
    "skipped": False,
    "product_id": product.id,
    "barcode": product.barcode,
    "total": total,
    "by_warehouse": warehouse_results,
  }


@transaction.atomic
def distribute_stocks_evenly_bulk(
  seller: Seller,
  *,
  product_ids: list[int] | None = None,
  user=None,
) -> dict:
  warehouses = get_enabled_seller_warehouses(seller)
  if len(warehouses) < 2:
    raise StockTransferError("Нужно минимум 2 включённых FBS-склада для распределения")

  qs = Product.objects.filter(seller=seller).select_related("cell").order_by("cell__number")
  if product_ids is not None:
    qs = qs.filter(pk__in=product_ids)
    if not qs.exists():
      raise StockTransferError("Не найдены товары для распределения")

  distributed = 0
  skipped = 0
  results: list[dict] = []
  errors: list[dict] = []

  for product in qs:
    try:
      result = distribute_product_stock_evenly(
        seller,
        product,
        warehouses=warehouses,
        user=user,
      )
      results.append(result)
      if result.get("skipped"):
        skipped += 1
      else:
        distributed += 1
    except (StockTransferError, WBStockError) as exc:
      errors.append({
        "product_id": product.id,
        "barcode": product.barcode,
        "error": str(exc),
      })

  if distributed == 0 and errors:
    raise StockTransferError(
      f"Не удалось распределить ни одного товара. Пример: {errors[0]['error']}",
    )

  return {
    "success": True,
    "distributed": distributed,
    "skipped": skipped,
    "errors": errors,
    "results": results,
  }


def format_transfer_item(
  *,
  barcode: str,
  quantity_requested: int,
  transfer: dict,
) -> dict:
  """Строка отчёта: было → стало по складам."""
  from_wh = transfer["from_warehouse"]
  to_wh = transfer["to_warehouse"]
  moved = int(transfer.get("quantity") or quantity_requested)
  total_before = int(from_wh["previous"]) + int(to_wh["previous"])
  total_after = int(transfer.get("total") or total_before)
  from_ok = int(from_wh["previous"]) - moved == int(from_wh["new"])
  to_ok = int(to_wh["previous"]) + moved == int(to_wh["new"])
  total_ok = total_before == total_after
  return {
    "barcode": barcode,
    "quantity_requested": quantity_requested,
    "quantity_moved": moved,
    "total_before": total_before,
    "total_after": total_after,
    "from_warehouse": {
      "name": from_wh["name"],
      "before": int(from_wh["previous"]),
      "after": int(from_wh["new"]),
    },
    "to_warehouse": {
      "name": to_wh["name"],
      "before": int(to_wh["previous"]),
      "after": int(to_wh["new"]),
    },
    "ok": from_ok and to_ok and total_ok,
  }


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

  item = format_transfer_item(
    barcode=product.barcode,
    quantity_requested=quantity,
    transfer=result,
  )

  return {
    "success": True,
    "ok": item["ok"],
    "product": {
      "id": product.id,
      "barcode": product.barcode,
      "crm_quantity": product.quantity,
    },
    "transfer": result,
    "item": item,
  }


def _source_quantity(stock_map: dict, barcode: str, from_warehouse_id: int) -> int:
  data = stock_map.get(barcode, {"by_warehouse": {}})
  return int((data.get("by_warehouse") or {}).get(from_warehouse_id, 0))


def transfer_stocks_bulk(
  seller: Seller,
  *,
  from_warehouse_id: int,
  to_warehouse_id: int,
  product_ids: list[int] | None = None,
  user=None,
) -> dict:
  """Перенести весь остаток каждого баркода со склада-источника на склад-назначение."""
  if from_warehouse_id == to_warehouse_id:
    raise StockTransferError("Выберите разные склады")

  qs = Product.objects.filter(seller=seller).select_related("cell").order_by("cell__number")
  if product_ids is not None:
    qs = qs.filter(pk__in=product_ids)
    if not qs.exists():
      raise StockTransferError("Не найдены товары для переноса")

  products = list(qs)
  if not products:
    raise StockTransferError("Нет товаров для переноса")

  try:
    stock_map = fetch_summed_wb_stocks(seller, [product.barcode for product in products])
  except WBStockError as exc:
    raise StockTransferError(str(exc)) from exc

  transferred = 0
  skipped = 0
  errors: list[dict] = []
  results: list[dict] = []
  items: list[dict] = []

  from_wh_name = ""
  to_wh_name = ""

  for product in products:
    quantity = _source_quantity(stock_map, product.barcode, from_warehouse_id)
    if quantity <= 0:
      skipped += 1
      results.append({
        "product_id": product.id,
        "barcode": product.barcode,
        "skipped": True,
        "reason": "zero_on_source",
      })
      continue
    try:
      payload = perform_stock_transfer(
        seller,
        product_id=product.id,
        from_warehouse_id=from_warehouse_id,
        to_warehouse_id=to_warehouse_id,
        quantity=quantity,
        user=user,
      )
      transferred += 1
      item = payload["item"]
      items.append(item)
      if not from_wh_name:
        from_wh_name = item["from_warehouse"]["name"]
        to_wh_name = item["to_warehouse"]["name"]
      results.append({
        "product_id": product.id,
        "barcode": product.barcode,
        "quantity": quantity,
        "skipped": False,
        "ok": item["ok"],
        "item": item,
      })
    except StockTransferError as exc:
      errors.append({
        "product_id": product.id,
        "barcode": product.barcode,
        "error": str(exc),
      })

  if transferred == 0 and errors:
    raise StockTransferError(
      f"Не удалось перенести ни одного товара. Пример: {errors[0]['error']}",
    )

  requested_count = len(products)
  all_ok = (
    len(errors) == 0
    and skipped == 0
    and transferred > 0
    and bool(items)
    and all(item["ok"] for item in items)
  )

  return {
    "success": True,
    "ok": all_ok,
    "transferred": transferred,
    "skipped": skipped,
    "errors": errors,
    "results": results,
    "items": items,
    "from_warehouse_name": from_wh_name,
    "to_warehouse_name": to_wh_name,
    "requested_count": requested_count,
  }
