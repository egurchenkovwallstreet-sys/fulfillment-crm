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
from apps.orders.services.wb_status import WB_STATUS_AFTER_DELIVER, WB_SUPPLIER_DELIVERY
from apps.sellers.models import Seller

# Старый формат: CRM-{wb_order_id}-...
CRM_SUPPLY_LEGACY_RE = re.compile(r"^CRM-(\d+)-")


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


def _fetch_supply_order_wb_ids(client, wb_supply: dict) -> list[int]:
  name = str(wb_supply.get("name") or "")
  legacy = CRM_SUPPLY_LEGACY_RE.match(name)
  if legacy:
    return [int(legacy.group(1))]

  supply_id = str(wb_supply.get("id") or "")
  if not supply_id:
    return []

  ids = client.fetch_supply_order_ids(supply_id)
  time.sleep(REQUEST_INTERVAL_SEC)
  return ids


def _sync_crm_orders_delivery_status(
  orders: list[Order],
  *,
  scanned_at: datetime | None = None,
) -> int:
  """Привести CRM-статус заказов к «в доставке» (complete + waiting) или SHIPPED после scanDt."""
  updated = 0
  for order in orders:
    update_fields: list[str] = []
    if order.wb_supplier_status != WB_SUPPLIER_DELIVERY:
      order.wb_supplier_status = WB_SUPPLIER_DELIVERY
      update_fields.append("wb_supplier_status")
    if scanned_at:
      if order.status != Order.Status.SHIPPED:
        order.status = Order.Status.SHIPPED
        update_fields.append("status")
      if order.in_delivery_at is None:
        order.in_delivery_at = scanned_at
        update_fields.append("in_delivery_at")
    else:
      if order.wb_status != WB_STATUS_AFTER_DELIVER:
        order.wb_status = WB_STATUS_AFTER_DELIVER
        update_fields.append("wb_status")
      if order.status != Order.Status.IN_DELIVERY:
        order.status = Order.Status.IN_DELIVERY
        update_fields.append("status")
      if order.in_delivery_at is None:
        order.in_delivery_at = timezone.now()
        update_fields.append("in_delivery_at")
    if update_fields:
      update_fields.append("updated_at")
      order.save(update_fields=update_fields)
      updated += 1

  return updated


def _process_wb_supply(
  seller: Seller,
  client,
  wb_supply: dict,
  *,
  stats: dict,
) -> None:
  wb_supply_id = str(wb_supply.get("id") or "")
  if not wb_supply_id:
    stats["skipped"] += 1
    return

  done = bool(wb_supply.get("done"))
  scanned_at = _parse_wb_datetime(wb_supply.get("scanDt") or wb_supply.get("scan_dt"))

  try:
    order_wb_ids = _fetch_supply_order_wb_ids(client, wb_supply)
  except WBApiError:
    stats["skipped"] += 1
    stats["fetch_errors"] += 1
    return

  stats["api_order_fetches"] += 1
  if not order_wb_ids:
    stats["skipped"] += 1
    return

  crm_orders = list(
    Order.objects.filter(seller=seller, wb_order_id__in=order_wb_ids)
    .select_related("product", "seller"),
  )
  if not crm_orders:
    stats["skipped"] += 1
    stats["orders_not_in_crm"] += len(order_wb_ids)
    return

  supply, was_created = Supply.objects.get_or_create(
    seller=seller,
    wb_supply_id=wb_supply_id,
    defaults={"status": Supply.Status.FORMING},
  )
  if was_created:
    stats["created"] += 1
  else:
    stats["updated"] += 1

  supply.orders.add(*crm_orders)
  stats["linked_orders"] += len(crm_orders)

  if done:
    update_fields: list[str] = []
    if supply.status != Supply.Status.CONFIRMED:
      supply.status = Supply.Status.CONFIRMED
      update_fields.extend(["status", "updated_at"])
    if not supply.supply_barcode_printed:
      supply.supply_barcode_printed = True
      update_fields.append("supply_barcode_printed")
    if scanned_at and supply.wb_scanned_at != scanned_at:
      supply.wb_scanned_at = scanned_at
      update_fields.append("wb_scanned_at")
    if update_fields:
      supply.save(update_fields=list(dict.fromkeys(update_fields)))

    stats["orders_status_updated"] += _sync_crm_orders_delivery_status(
      crm_orders,
      scanned_at=scanned_at,
    )
  else:
    refresh_supply_readiness(supply)


def sync_supplies_from_wb(
  seller: Seller,
  *,
  include_closed: bool = True,
  closed_days: int = 30,
  max_open_supply_fetches: int = 50,
) -> dict:
  """
  Подтянуть поставки из WB в CRM.

  Поставки с done=true (переданы в доставку, в т.ч. из ЛК WB) обрабатываются:
  заказы привязываются к Supply, статусы обновляются. Списание CRM-остатков — только
  при печати FBS-стикера; заказы «в доставке» остаток не меняют.
  """
  client = _get_client(seller)
  try:
    wb_supplies = client.fetch_supplies()
  except WBApiError as exc:
    raise AssemblyError(str(exc)) from exc

  cutoff = timezone.now() - timedelta(days=closed_days)
  stats = {
    "created": 0,
    "updated": 0,
    "linked_orders": 0,
    "skipped": 0,
    "api_order_fetches": 0,
    "fetch_errors": 0,
    "orders_not_in_crm": 0,
    "orders_status_updated": 0,
    "wb_supplies_total": len(wb_supplies),
    "done_supplies": 0,
    "open_supplies": 0,
  }

  done_supplies: list[dict] = []
  open_supplies: list[dict] = []

  for wb_supply in wb_supplies:
    if not wb_supply.get("id"):
      stats["skipped"] += 1
      continue
    if bool(wb_supply.get("done")):
      if not include_closed:
        stats["skipped"] += 1
        continue
      created_at = _parse_wb_datetime(
        wb_supply.get("createdAt") or wb_supply.get("created_at"),
      )
      if created_at and created_at < cutoff:
        stats["skipped"] += 1
        continue
      done_supplies.append(wb_supply)
    else:
      open_supplies.append(wb_supply)

  for wb_supply in done_supplies:
    stats["done_supplies"] += 1
    _process_wb_supply(seller, client, wb_supply, stats=stats)

  open_fetches = 0
  for wb_supply in open_supplies:
    if open_fetches >= max_open_supply_fetches:
      stats["skipped"] += 1
      continue
    stats["open_supplies"] += 1
    open_fetches += 1
    _process_wb_supply(seller, client, wb_supply, stats=stats)

  return stats


def sync_supply_scan_dates(seller: Seller, client=None) -> dict:
  """
  Обновить wb_scanned_at по scanDt из WB API.
  После сканирования ШК поставки на складе заказы уходят из вкладки «В доставке».
  """
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

    orders = list(supply.orders.all())
    orders_closed += _sync_crm_orders_delivery_status(orders, scanned_at=scanned_at)

  return {
    "supplies_checked": len(wb_supplies),
    "supplies_scanned": supplies_scanned,
    "orders_closed": orders_closed,
  }
