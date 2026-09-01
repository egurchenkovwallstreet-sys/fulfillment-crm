"""Поиск отгрузок через ЛК WB без прохождения сборки в CRM."""
from __future__ import annotations

import time
from datetime import timedelta

from django.db.models import Count
from django.utils import timezone

from apps.integrations.wb_client import REQUEST_INTERVAL_SEC, WBApiError
from apps.orders.models import OffCrmShipment, Order
from apps.orders.services.assembly import AssemblyError, _get_client, format_sticker_number
from apps.orders.services.supply_sync import _parse_wb_datetime
from apps.sellers.models import Seller, SellerWarehouse
from apps.sellers.services.warehouse_filter import get_enabled_wb_warehouse_ids, is_warehouse_enabled
from apps.warehouse.services.stock_deduction import (
  StockDeductionError,
  deduct_stock_for_off_crm_shipment,
  normalize_sticker_key,
  order_has_crm_shipment_deduction,
)


class OffCrmShipmentError(Exception):
  pass


def _crm_sticker_keys(seller: Seller) -> set[str]:
  keys: set[str] = set()
  rows = (
    Order.objects.filter(seller=seller)
    .exclude(sticker_part_a="")
    .exclude(sticker_part_b="")
    .values_list("sticker_part_a", "sticker_part_b")
  )
  for part_a, part_b in rows:
    key = normalize_sticker_key(part_a, part_b)
    if key:
      keys.add(key)
  return keys


def _warehouse_name_map(seller: Seller) -> dict[int, str]:
  return {
    wh_id: name or f"Склад #{wh_id}"
    for wh_id, name in SellerWarehouse.objects.filter(seller=seller).values_list(
      "wb_warehouse_id",
      "name",
    )
  }


def pending_off_crm_count(*, seller_ids: list[int] | None = None) -> int:
  qs = OffCrmShipment.objects.filter(status=OffCrmShipment.Status.PENDING)
  if seller_ids is not None:
    qs = qs.filter(seller_id__in=seller_ids)
  return qs.count()


def off_crm_summary_by_seller(*, seller_ids: list[int] | None = None) -> list[dict]:
  qs = (
    OffCrmShipment.objects.filter(status=OffCrmShipment.Status.PENDING)
    .values("seller_id", "seller__company_name")
    .annotate(pending_count=Count("id"))
    .order_by("-pending_count", "seller__company_name")
  )
  if seller_ids is not None:
    qs = qs.filter(seller_id__in=seller_ids)
  return [
    {
      "seller_id": row["seller_id"],
      "seller_name": row["seller__company_name"] or f"Селлер #{row['seller_id']}",
      "pending_count": row["pending_count"],
    }
    for row in qs
  ]


def off_crm_shipments_for_seller(seller: Seller) -> list[dict]:
  rows = (
    OffCrmShipment.objects.filter(
      seller=seller,
      status=OffCrmShipment.Status.PENDING,
    )
    .order_by("-shipped_at", "-detected_at")
  )
  return [
    {
      "id": row.id,
      "wb_order_id": row.wb_order_id,
      "barcode": row.barcode,
      "sticker_number": row.sticker_number or format_sticker_number(row),
      "warehouse_name": row.warehouse_name or "—",
      "wb_warehouse_id": row.wb_warehouse_id,
      "quantity": row.quantity,
      "shipped_at": row.shipped_at.isoformat() if row.shipped_at else None,
      "wb_supply_id": row.wb_supply_id,
      "detected_at": row.detected_at.isoformat(),
    }
    for row in rows
  ]


def scan_off_crm_shipments(
  seller: Seller,
  *,
  days: int = 30,
) -> dict:
  """Ежедневная проверка: отгрузки done=true на включённых складах без стикера CRM."""
  enabled = get_enabled_wb_warehouse_ids(seller)
  if not enabled:
    return {"skipped": True, "reason": "no_enabled_warehouses"}

  client = _get_client(seller)
  try:
    wb_supplies = client.fetch_supplies()
  except WBApiError as exc:
    raise AssemblyError(str(exc)) from exc

  crm_keys = _crm_sticker_keys(seller)
  warehouse_names = _warehouse_name_map(seller)
  cutoff = timezone.now() - timedelta(days=days)

  stats = {
    "supplies_checked": 0,
    "orders_checked": 0,
    "candidates_created": 0,
    "candidates_updated": 0,
    "skipped_crm_sticker": 0,
    "skipped_warehouse": 0,
    "skipped_no_barcode": 0,
    "skipped_already_deducted": 0,
    "api_errors": 0,
  }

  for wb_supply in wb_supplies:
    if not wb_supply.get("done"):
      continue

    created_at = _parse_wb_datetime(
      wb_supply.get("createdAt") or wb_supply.get("created_at"),
    )
    if created_at and created_at < cutoff:
      continue

    wb_supply_id = str(wb_supply.get("id") or "")
    if not wb_supply_id:
      continue

    stats["supplies_checked"] += 1
    shipped_at = _parse_wb_datetime(
      wb_supply.get("scanDt")
      or wb_supply.get("scan_dt")
      or wb_supply.get("closedAt")
      or wb_supply.get("closed_at")
      or wb_supply.get("createdAt")
      or wb_supply.get("created_at"),
    )

    try:
      order_ids = client.fetch_supply_order_ids(wb_supply_id)
    except WBApiError:
      stats["api_errors"] += 1
      continue
    time.sleep(REQUEST_INTERVAL_SEC)

    if not order_ids:
      continue

    crm_orders = {
      order.wb_order_id: order
      for order in Order.objects.filter(seller=seller, wb_order_id__in=order_ids)
    }

    eligible_ids: list[int] = []
    for wb_order_id in order_ids:
      crm_order = crm_orders.get(wb_order_id)
      wh_id = crm_order.wb_warehouse_id if crm_order else None
      if wh_id is not None and not is_warehouse_enabled(seller, wh_id):
        stats["skipped_warehouse"] += 1
        continue
      if wh_id is None:
        stats["skipped_warehouse"] += 1
        continue
      eligible_ids.append(wb_order_id)

    if not eligible_ids:
      continue

    try:
      stickers = client.fetch_order_stickers(eligible_ids)
    except WBApiError:
      stats["api_errors"] += 1
      continue

    for sticker in stickers:
      raw_order_id = sticker.get("orderId")
      if raw_order_id is None:
        continue
      wb_order_id = int(raw_order_id)
      stats["orders_checked"] += 1

      part_a = str(sticker.get("partA") or "")
      part_b = str(sticker.get("partB") or "")
      sticker_key = normalize_sticker_key(part_a, part_b)
      if not sticker_key:
        continue

      if sticker_key in crm_keys:
        stats["skipped_crm_sticker"] += 1
        continue

      crm_order = crm_orders.get(wb_order_id)
      if crm_order and order_has_crm_shipment_deduction(crm_order):
        stats["skipped_already_deducted"] += 1
        continue

      barcode = (crm_order.barcode if crm_order else "").strip()
      if not barcode:
        stats["skipped_no_barcode"] += 1
        continue

      wh_id = crm_order.wb_warehouse_id if crm_order else None
      wh_name = warehouse_names.get(wh_id, "") if wh_id else ""
      sticker_number = f"{part_a} / {part_b}" if part_a and part_b else (part_a or part_b)

      obj, created = OffCrmShipment.objects.update_or_create(
        seller=seller,
        sticker_part_a=part_a,
        sticker_part_b=part_b,
        defaults={
          "crm_order": crm_order,
          "wb_order_id": wb_order_id,
          "barcode": barcode,
          "sticker_number": sticker_number,
          "wb_supply_id": wb_supply_id,
          "wb_warehouse_id": wh_id,
          "warehouse_name": wh_name,
          "quantity": 1,
          "shipped_at": shipped_at,
          "status": OffCrmShipment.Status.PENDING,
        },
      )
      if created:
        stats["candidates_created"] += 1
      else:
        stats["candidates_updated"] += 1

  return stats


def scan_off_crm_shipments_all_sellers(*, days: int = 30) -> dict:
  sellers = (
    Seller.objects.filter(is_active=True, wb_enabled=True)
    .exclude(wb_api_token_encrypted="")
  )
  results = []
  errors = []
  for seller in sellers:
    try:
      stats = scan_off_crm_shipments(seller, days=days)
      results.append({"seller_id": seller.id, **stats})
    except AssemblyError as exc:
      errors.append({"seller_id": seller.id, "error": str(exc)})
  return {"results": results, "errors": errors}


def deduct_off_crm_shipment(shipment_id: int, *, user=None) -> dict:
  shipment = (
    OffCrmShipment.objects.select_related("seller", "crm_order")
    .filter(pk=shipment_id)
    .first()
  )
  if not shipment:
    raise OffCrmShipmentError("Запись не найдена")
  if shipment.status != OffCrmShipment.Status.PENDING:
    raise OffCrmShipmentError("Решение по этой отгрузке уже принято")

  sticker_number = shipment.sticker_number or format_sticker_number(shipment)
  try:
    stock = deduct_stock_for_off_crm_shipment(
      seller=shipment.seller,
      barcode=shipment.barcode,
      wb_order_id=shipment.wb_order_id,
      sticker_number=sticker_number,
      user=user,
    )
  except StockDeductionError as exc:
    raise OffCrmShipmentError(str(exc)) from exc

  shipment.status = OffCrmShipment.Status.DEDUCTED
  shipment.resolved_by = user
  shipment.resolved_at = timezone.now()
  shipment.save(update_fields=["status", "resolved_by", "resolved_at"])

  return {"shipment_id": shipment.id, "status": shipment.status, "stock": stock}


def skip_off_crm_shipment(shipment_id: int, *, user=None) -> dict:
  shipment = OffCrmShipment.objects.filter(pk=shipment_id).first()
  if not shipment:
    raise OffCrmShipmentError("Запись не найдена")
  if shipment.status != OffCrmShipment.Status.PENDING:
    raise OffCrmShipmentError("Решение по этой отгрузке уже принято")

  shipment.status = OffCrmShipment.Status.SKIPPED
  shipment.resolved_by = user
  shipment.resolved_at = timezone.now()
  shipment.save(update_fields=["status", "resolved_by", "resolved_at"])
  return {"shipment_id": shipment.id, "status": shipment.status}
