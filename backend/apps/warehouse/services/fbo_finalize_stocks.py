"""Списание CRM и выставление остатков WB после сборки FBO."""
from __future__ import annotations

from collections import defaultdict

from django.db import transaction
from django.utils import timezone

from apps.integrations.models import AuditLog
from apps.sellers.models import Seller
from apps.warehouse.models import (
  FboAssemblyBox,
  FboAssemblyLine,
  FboAssemblySession,
  Product,
  StockOperation,
)
from apps.warehouse.services.cells import refresh_cell_occupied
from apps.warehouse.services.fbo_assembly import FboAssemblyError
from apps.warehouse.services.live_wb_orders import (
  LiveWbOrdersError,
  count_live_open_orders_for_warehouses,
)
from apps.warehouse.services.wb_stocks import (
  WBStockError,
  fetch_summed_wb_stocks,
  get_enabled_seller_warehouses,
  set_wb_stock_absolute,
)


def _aggregate_fbo_quantities(session: FboAssemblySession) -> dict[str, tuple[Product, int]]:
  totals: dict[str, int] = defaultdict(int)
  products: dict[str, Product] = {}
  lines = FboAssemblyLine.objects.filter(box__session=session).values_list(
    "barcode",
    "quantity",
    "product_id",
  )
  for barcode, qty, product_id in lines:
    if not barcode or not qty:
      continue
    totals[barcode] += int(qty)
    if barcode not in products and product_id:
      product = Product.objects.filter(pk=product_id).first()
      if product:
        products[barcode] = product
  result: dict[str, tuple[Product, int]] = {}
  for barcode, total_qty in totals.items():
    product = products.get(barcode)
    if product is None:
      product = Product.objects.filter(
        seller=session.seller,
        marketplace=session.marketplace,
        barcode=barcode,
      ).first()
    if not product:
      raise FboAssemblyError(f"Товар не найден в CRM: {barcode}")
    result[barcode] = (product, total_qty)
  return result


def _warehouse_amount_targets(current_by_wh: dict[int, int], target_total: int) -> dict[int, int]:
  """Разложить целевой остаток по обслуживаемым складам (сумма = target_total)."""
  target_total = max(0, int(target_total))
  wh_ids = list(current_by_wh.keys())
  if not wh_ids:
    return {}
  current_total = sum(int(current_by_wh.get(wid, 0)) for wid in wh_ids)
  if current_total == target_total:
    return {wid: int(current_by_wh.get(wid, 0)) for wid in wh_ids}

  result = {wid: int(current_by_wh.get(wid, 0)) for wid in wh_ids}
  if current_total == 0:
    result[wh_ids[0]] = target_total
    for wid in wh_ids[1:]:
      result[wid] = 0
    return result

  if target_total > current_total:
    extra = target_total - current_total
    primary = max(wh_ids, key=lambda wid: result[wid])
    result[primary] = result[primary] + extra
    return result

  to_remove = current_total - target_total
  for wh_id in sorted(wh_ids, key=lambda wid: result[wid], reverse=True):
    if to_remove <= 0:
      break
    take = min(result[wh_id], to_remove)
    result[wh_id] -= take
    to_remove -= take
  return result


@transaction.atomic
def finalize_fbo_session_stocks(session: FboAssemblySession, *, user) -> dict:
  session = (
    FboAssemblySession.objects.select_for_update()
    .select_related("seller")
    .get(pk=session.pk)
  )
  if session.status != FboAssemblySession.Status.COMPLETED:
    raise FboAssemblyError("Сначала закройте сборку FBO")
  if session.stocks_finalized_at:
    raise FboAssemblyError("Остатки по этой сборке уже списаны")
  if session.boxes.filter(status=FboAssemblyBox.Status.OPEN).exists():
    raise FboAssemblyError("Закройте все короба перед списанием")

  aggregates = _aggregate_fbo_quantities(session)
  if not aggregates:
    raise FboAssemblyError("В сборке нет отсканированных товаров")

  seller: Seller = session.seller
  warehouses = get_enabled_seller_warehouses(seller)
  if not warehouses:
    raise FboAssemblyError("Нет включённых FBS-складов WB у селлера")

  barcodes = list(aggregates.keys())
  try:
    stock_map = fetch_summed_wb_stocks(seller, barcodes)
  except WBStockError as exc:
    raise FboAssemblyError(str(exc)) from exc

  line_reports: list[dict] = []

  for barcode, (product, fbo_qty) in aggregates.items():
    product = Product.objects.select_for_update().select_related("cell").get(pk=product.pk)
    crm_was = int(product.quantity or 0)
    try:
      wb_new_count, wb_picking_count, wb_reserved_total = count_live_open_orders_for_warehouses(
        seller,
        barcode,
        warehouses,
      )
    except LiveWbOrdersError as exc:
      raise FboAssemblyError(str(exc)) from exc

    crm_after = max(0, crm_was - fbo_qty)
    wb_target_total = max(0, crm_was - fbo_qty - wb_reserved_total)

    if crm_was > 0 or fbo_qty > 0:
      product.quantity = crm_after
      product.save(update_fields=["quantity", "updated_at"])
      if product.cell_id:
        refresh_cell_occupied(product.cell)
      if fbo_qty > 0:
        StockOperation.objects.create(
          product=product,
          operation_type=StockOperation.OperationType.SHIPMENT,
          quantity=fbo_qty,
          performed_by=user,
          comment=(
            f"Сборка FBO #{session.id}: {fbo_qty} шт., баркод {barcode}, "
            f"остаток CRM {crm_after} шт."
          ),
        )

    stock_entry = stock_map.get(barcode) or {"total": 0, "by_warehouse": {}}
    by_wh = stock_entry.get("by_warehouse") or {}
    wb_total_before = int(stock_entry.get("total") or 0)
    current_by_wh = {wh.id: int(by_wh.get(wh.id, 0)) for wh in warehouses}
    target_by_wh = _warehouse_amount_targets(current_by_wh, wb_target_total)

    warehouse_details: list[dict] = []
    for wh in warehouses:
      prev = current_by_wh.get(wh.id, 0)
      new_amount = target_by_wh.get(wh.id, 0)
      if prev == new_amount:
        warehouse_details.append({
          "warehouse_id": wh.id,
          "warehouse_name": wh.name or f"Склад #{wh.wb_warehouse_id}",
          "wb_warehouse_id": wh.wb_warehouse_id,
          "before": prev,
          "after": new_amount,
          "changed": False,
        })
        continue
      try:
        set_wb_stock_absolute(seller, wh, barcode, new_amount, product=product)
      except WBStockError as exc:
        raise FboAssemblyError(f"{barcode}: {exc}") from exc
      warehouse_details.append({
        "warehouse_id": wh.id,
        "warehouse_name": wh.name or f"Склад #{wh.wb_warehouse_id}",
        "wb_warehouse_id": wh.wb_warehouse_id,
        "before": prev,
        "after": new_amount,
        "changed": True,
      })

    line_reports.append({
      "barcode": barcode,
      "crm_was": crm_was,
      "fbo_qty": fbo_qty,
      "wb_new_orders": wb_new_count,
      "wb_picking_orders": wb_picking_count,
      "wb_reserved_total": wb_reserved_total,
      "crm_after": crm_after,
      "wb_total_before": wb_total_before,
      "wb_total_after": wb_target_total,
      "check_crm": crm_was - fbo_qty == crm_after,
      "check_wb": crm_was - fbo_qty - wb_reserved_total == wb_target_total,
      "warehouses": warehouse_details,
    })

  session.stocks_finalized_at = timezone.now()
  session.save(update_fields=["stocks_finalized_at"])

  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.OTHER,
    message=f"FBO #{session.id}: списание CRM и остатки WB",
    details={"session_id": session.id, "lines": len(line_reports)},
  )

  return {
    "session_id": session.id,
    "finalized_at": session.stocks_finalized_at.isoformat(),
    "lines": line_reports,
  }
