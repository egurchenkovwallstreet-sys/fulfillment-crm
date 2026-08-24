"""Синхронизация поставок CRM с Wildberries FBS."""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone as dt_timezone

from django.utils import timezone

from apps.integrations.wb_client import REQUEST_INTERVAL_SEC, WBApiError
from apps.orders.models import Order, Supply
from apps.orders.services.assembly import AssemblyError, _get_client
from apps.orders.services.supply_flow import refresh_supply_readiness
from apps.sellers.models import Seller
from apps.warehouse.services.stock_deduction import deduct_stock_for_confirmed_supply

CRM_SUPPLY_NAME_RE = re.compile(r"^CRM-(\d+)-")


def _parse_wb_datetime(value) -> datetime | None:
  if not value:
    return None
  if isinstance(value, datetime):
    if timezone.is_naive(value):
      return timezone.make_aware(value, dt_timezone.utc)
    return value
  text = str(value).strip()
  if not text:
    return None
  text = text.replace("Z", "+00:00")
  try:
    parsed = datetime.fromisoformat(text)
  except ValueError:
    return None
  if timezone.is_naive(parsed):
    return timezone.make_aware(parsed, dt_timezone.utc)
  return parsed


def _order_wb_ids_for_supply(client, wb_supply: dict, *, allow_api: bool) -> list[int]:
  name = str(wb_supply.get("name") or "")
  match = CRM_SUPPLY_NAME_RE.match(name)
  if match:
    return [int(match.group(1))]

  if not allow_api:
    return []

  supply_id = str(wb_supply.get("id") or "")
  if not supply_id:
    return []

  ids = client.fetch_supply_order_ids(supply_id)
  time.sleep(REQUEST_INTERVAL_SEC)
  return ids


def sync_supplies_from_wb(
  seller: Seller,
  *,
  include_closed: bool = False,
  closed_days: int = 30,
  max_api_order_fetches: int = 50,
) -> dict:
  """
  Подтянуть поставки из WB в CRM.
  Имена CRM-{wb_order_id}-* разбираются без доп. запросов к API.
  """
  client = _get_client(seller)
  try:
    wb_supplies = client.fetch_supplies()
  except WBApiError as exc:
    raise AssemblyError(str(exc)) from exc

  cutoff = timezone.now() - timedelta(days=closed_days)
  created = 0
  updated = 0
  linked_orders = 0
  skipped = 0
  api_order_fetches = 0
  stock_deducted = 0
  stock_errors = 0

  for wb_supply in wb_supplies:
    done = bool(wb_supply.get("done"))
    if done and not include_closed:
      skipped += 1
      continue

    if done:
      created_at = _parse_wb_datetime(
        wb_supply.get("createdAt") or wb_supply.get("created_at"),
      )
      if created_at and created_at < cutoff:
        skipped += 1
        continue

    wb_supply_id = str(wb_supply.get("id") or "")
    if not wb_supply_id:
      skipped += 1
      continue

    name = str(wb_supply.get("name") or "")
    if CRM_SUPPLY_NAME_RE.match(name):
      order_wb_ids = _order_wb_ids_for_supply(client, wb_supply, allow_api=False)
    elif api_order_fetches < max_api_order_fetches:
      order_wb_ids = _order_wb_ids_for_supply(client, wb_supply, allow_api=True)
      api_order_fetches += 1
    else:
      skipped += 1
      continue

    if not order_wb_ids:
      skipped += 1
      continue

    crm_orders = list(
      Order.objects.filter(seller=seller, wb_order_id__in=order_wb_ids)
      .select_related("product", "seller"),
    )
    if not crm_orders:
      skipped += 1
      continue

    supply, was_created = Supply.objects.get_or_create(
      seller=seller,
      wb_supply_id=wb_supply_id,
      defaults={"status": Supply.Status.FORMING},
    )
    if was_created:
      created += 1
    else:
      updated += 1

    supply.orders.set(crm_orders)
    linked_orders += len(crm_orders)

    if done:
      update_fields = []
      if supply.status != Supply.Status.CONFIRMED:
        supply.status = Supply.Status.CONFIRMED
        update_fields.extend(["status", "updated_at"])
      if not supply.supply_barcode_printed:
        supply.supply_barcode_printed = True
        update_fields.append("supply_barcode_printed")
      scanned_at = _parse_wb_datetime(wb_supply.get("scanDt") or wb_supply.get("scan_dt"))
      if scanned_at and supply.wb_scanned_at != scanned_at:
        supply.wb_scanned_at = scanned_at
        update_fields.append("wb_scanned_at")
      if update_fields:
        supply.save(update_fields=list(dict.fromkeys(update_fields)))

      deduction = deduct_stock_for_confirmed_supply(supply)
      stock_deducted += deduction["deducted"]
      stock_errors += len(deduction["errors"])
    else:
      refresh_supply_readiness(supply)

  return {
    "created": created,
    "updated": updated,
    "linked_orders": linked_orders,
    "skipped": skipped,
    "api_order_fetches": api_order_fetches,
    "wb_supplies_total": len(wb_supplies),
    "stock_deducted": stock_deducted,
    "stock_errors": stock_errors,
  }


def sync_supply_scan_dates(seller: Seller, client=None) -> dict:
  """
  Обновить wb_scanned_at по scanDt из WB API.
  После сканирования ШК поставки на складе заказы уходят из вкладки «В доставке».
  """
  from apps.orders.services.assembly import _get_client

  if client is None:
    client = _get_client(seller)

  try:
    wb_supplies = client.fetch_supplies()
  except WBApiError as exc:
    raise AssemblyError(str(exc)) from exc

  scan_by_id = {}
  for wb_supply in wb_supplies:
    wb_supply_id = str(wb_supply.get("id") or "")
    if not wb_supply_id:
      continue
    scanned_at = _parse_wb_datetime(wb_supply.get("scanDt") or wb_supply.get("scan_dt"))
    if scanned_at:
      scan_by_id[wb_supply_id] = scanned_at

  if not scan_by_id:
    return {"supplies_checked": len(wb_supplies), "supplies_scanned": 0, "orders_closed": 0}

  supplies = list(
    Supply.objects.filter(seller=seller, wb_supply_id__in=scan_by_id.keys())
    .prefetch_related("orders")
  )
  now = timezone.now()
  supplies_scanned = 0
  orders_closed = 0

  for supply in supplies:
    scanned_at = scan_by_id.get(supply.wb_supply_id)
    if not scanned_at:
      continue
    if supply.wb_scanned_at == scanned_at:
      continue

    supply.wb_scanned_at = scanned_at
    supply.save(update_fields=["wb_scanned_at", "updated_at"])
    supplies_scanned += 1

    closed = supply.orders.filter(status=Order.Status.IN_DELIVERY).update(
      status=Order.Status.SHIPPED,
      updated_at=now,
    )
    orders_closed += closed

  return {
    "supplies_checked": len(wb_supplies),
    "supplies_scanned": supplies_scanned,
    "orders_closed": orders_closed,
  }
