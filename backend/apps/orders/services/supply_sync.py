"""Синхронизация поставок CRM с Wildberries FBS."""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta, timezone as dt_timezone

from django.utils import timezone

from apps.integrations.wb_client import REQUEST_INTERVAL_SEC, WBApiError
from apps.orders.models import Order, Supply
from apps.orders.services.assembly import AssemblyError, _get_client
from apps.orders.services.supply_flow import delivery_stage_supplies_queryset, refresh_supply_readiness
from apps.orders.services.wb_status import (
  WB_STATUS_AFTER_DELIVER,
  WB_SUPPLIER_DELIVERY,
  maybe_set_wb_sorted_at,
  order_accepted_at_wb_sc,
)
from apps.sellers.models import Seller

logger = logging.getLogger(__name__)

# Старый формат: CRM-{wb_order_id}-...
CRM_SUPPLY_LEGACY_RE = re.compile(r"^CRM-(\d+)-")


def _unwrap_wb_supply_dict(payload: dict) -> dict:
  if not payload:
    return {}
  for key in ("supply", "data", "result"):
    nested = payload.get(key)
    if isinstance(nested, dict) and (
      nested.get("id") or nested.get("scanDt") or nested.get("scan_dt")
    ):
      return nested
  return payload


def _wb_supply_scanned_at(wb_supply: dict) -> datetime | None:
  """
  Момент приёмки поставки на складе WB — только scanDt (скан ШК поставки).
  closedAt ставится при передаче в доставку, до физической приёмки на СЦ.
  """
  wb_supply = _unwrap_wb_supply_dict(wb_supply)
  return _parse_wb_datetime(wb_supply.get("scanDt") or wb_supply.get("scan_dt"))


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


def close_order_accepted_at_wb_sc(
  order: Order,
  *,
  seller: Seller,
  supplier_status: str | None = None,
  wb_status: str | None = None,
  record_charges: bool = True,
) -> bool:
  """Закрыть заказ, уже принятый на СЦ WB поштучно (без scanDt поставки)."""
  update_fields: list[str] = []
  supplier = (supplier_status or order.wb_supplier_status or WB_SUPPLIER_DELIVERY).strip()
  wb = (wb_status or order.wb_status or "sorted").strip()
  if order.wb_supplier_status != supplier:
    order.wb_supplier_status = supplier
    update_fields.append("wb_supplier_status")
  if order.wb_status != wb:
    order.wb_status = wb
    update_fields.append("wb_status")
  if maybe_set_wb_sorted_at(order, supplier, wb):
    update_fields.append("wb_sorted_at")
  if order.status != Order.Status.SHIPPED:
    order.status = Order.Status.SHIPPED
    update_fields.append("status")
  changed = bool(update_fields)
  if changed:
    update_fields.append("updated_at")
    order.save(update_fields=update_fields)
  return changed


def _sync_crm_orders_delivery_status(
  orders: list[Order],
  *,
  seller: Seller | None = None,
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
      if order_accepted_at_wb_sc(order):
        if seller is not None and order.status != Order.Status.SHIPPED:
          if close_order_accepted_at_wb_sc(order, seller=seller):
            updated += 1
        continue
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


def record_shipment_charges_for_orders(orders: list[Order], *, seller: Seller) -> None:
  """Начисления отгрузки — только при печати FBS-стикера в CRM (sticker_billing)."""
  del orders, seller


def _finalize_supply_scan(
  supply: Supply,
  orders: list[Order],
  *,
  seller: Seller,
  scanned_at: datetime,
) -> int:
  """Закрыть поставку после scanDt на WB: убрать из «В доставке», зафиксировать начисление."""
  stuck_orders = [order for order in orders if order.status == Order.Status.IN_DELIVERY]
  if supply.wb_scanned_at == scanned_at and not stuck_orders:
    return 0

  if supply.wb_scanned_at != scanned_at:
    supply.wb_scanned_at = scanned_at
    supply.save(update_fields=["wb_scanned_at", "updated_at"])

  closed = _sync_crm_orders_delivery_status(orders, seller=seller, scanned_at=scanned_at)
  if closed or stuck_orders:
    record_shipment_charges_for_orders(orders, seller=seller)
  return closed


def _build_wb_supply_scan_index(wb_supplies: list[dict]) -> dict[str, datetime]:
  scan_by_id: dict[str, datetime] = {}
  for wb_supply in wb_supplies:
    wb_supply_id = str(wb_supply.get("id") or "")
    if not wb_supply_id:
      continue
    scanned_at = _wb_supply_scanned_at(wb_supply)
    if scanned_at:
      scan_by_id[wb_supply_id] = scanned_at
  return scan_by_id


def _fetch_supply_detail_raw(client, wb_supply_id: str) -> dict | None:
  """GET /api/v3/supplies/{id}. None — ошибка API (не «нет scanDt»)."""
  try:
    detail = _unwrap_wb_supply_dict(client.fetch_supply(wb_supply_id))
  except WBApiError:
    return None
  time.sleep(REQUEST_INTERVAL_SEC)
  return detail


def _fetch_supply_scanned_at_detail(client, wb_supply_id: str) -> datetime | None:
  """scanDt из detail API; None если ошибка или поле пустое."""
  detail = _fetch_supply_detail_raw(client, wb_supply_id)
  if detail is None:
    return None
  return _wb_supply_scanned_at(detail)


def _find_crm_supply_for_wb_scan(
  seller: Seller,
  wb_supply_id: str,
  order_wb_ids: list[int] | None = None,
) -> Supply | None:
  supply = Supply.objects.filter(seller=seller, wb_supply_id=wb_supply_id).first()
  if supply:
    return supply
  if not order_wb_ids:
    return None
  return (
    Supply.objects.filter(
      seller=seller,
      wb_scanned_at__isnull=True,
      orders__wb_order_id__in=order_wb_ids,
    )
    .distinct()
    .order_by("-updated_at")
    .first()
  )


def _ensure_supply_wb_id(supply: Supply, wb_supply_id: str) -> None:
  if supply.wb_supply_id == wb_supply_id:
    return
  supply.wb_supply_id = wb_supply_id
  supply.save(update_fields=["wb_supply_id", "updated_at"])


def _apply_scan_to_crm_supply(
  seller: Seller,
  *,
  wb_supply_id: str,
  scanned_at: datetime,
  order_wb_ids: list[int] | None = None,
  client=None,
) -> tuple[int, bool]:
  """Найти CRM-поставку по ID или заказам и закрыть после scanDt."""
  supply = _find_crm_supply_for_wb_scan(seller, wb_supply_id, order_wb_ids)
  if not supply and client is not None and order_wb_ids is None:
    try:
      order_wb_ids = client.fetch_supply_order_ids(wb_supply_id)
      time.sleep(REQUEST_INTERVAL_SEC)
    except WBApiError:
      order_wb_ids = []
    supply = _find_crm_supply_for_wb_scan(seller, wb_supply_id, order_wb_ids)
  if not supply:
    return 0, False

  _ensure_supply_wb_id(supply, wb_supply_id)
  if supply.status != Supply.Status.CONFIRMED:
    supply.status = Supply.Status.CONFIRMED
    supply.save(update_fields=["status", "updated_at"])

  orders = list(supply.orders.all())
  if not orders and client is not None:
    if order_wb_ids is None:
      try:
        order_wb_ids = client.fetch_supply_order_ids(wb_supply_id)
        time.sleep(REQUEST_INTERVAL_SEC)
      except WBApiError:
        order_wb_ids = []
    if order_wb_ids:
      orders = list(
        Order.objects.filter(seller=seller, wb_order_id__in=order_wb_ids),
      )
      if orders:
        supply.orders.add(*orders)
  was_pending = supply.wb_scanned_at is None or any(
    order.status == Order.Status.IN_DELIVERY for order in orders
  )
  closed = _finalize_supply_scan(
    supply,
    orders,
    seller=seller,
    scanned_at=scanned_at,
  )
  return closed, was_pending and (closed or supply.wb_scanned_at is not None)


def _apply_stuck_supply_detail_scans(
  seller: Seller,
  client,
  wb_supplies: list[dict],
) -> tuple[int, int]:
  """Проверить scanDt в detail API для всех CRM-поставок без wb_scanned_at."""
  scan_by_id = _build_wb_supply_scan_index(wb_supplies)
  supplies_scanned = 0
  orders_closed = 0

  pending = list(_pending_scan_supplies_qs(seller).prefetch_related("orders"))
  for supply in pending:
    wb_supply_id = str(supply.wb_supply_id or "")
    if not wb_supply_id:
      continue
    scanned_at = scan_by_id.get(wb_supply_id)
    if not scanned_at:
      scanned_at = _fetch_supply_scanned_at_detail(client, wb_supply_id)
    if not scanned_at:
      continue
    closed, counted = _apply_scan_to_crm_supply(
      seller,
      wb_supply_id=wb_supply_id,
      scanned_at=scanned_at,
      order_wb_ids=[order.wb_order_id for order in supply.orders.all()],
      client=client,
    )
    if counted:
      supplies_scanned += 1
      orders_closed += closed

  return supplies_scanned, orders_closed


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
  scanned_at = _wb_supply_scanned_at(wb_supply)

  try:
    order_wb_ids = _fetch_supply_order_wb_ids(client, wb_supply)
  except WBApiError:
    stats["fetch_errors"] += 1
    if done and scanned_at:
      existing = (
        Supply.objects.filter(seller=seller, wb_supply_id=wb_supply_id)
        .prefetch_related("orders")
        .first()
      )
      if existing:
        crm_orders = list(existing.orders.all())
        if crm_orders:
          stats["orders_status_updated"] += _finalize_supply_scan(
            existing,
            crm_orders,
            seller=seller,
            scanned_at=scanned_at,
          )
    stats["skipped"] += 1
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
    if update_fields:
      supply.save(update_fields=list(dict.fromkeys(update_fields)))

    if scanned_at:
      stats["orders_status_updated"] += _finalize_supply_scan(
        supply,
        crm_orders,
        seller=seller,
        scanned_at=scanned_at,
      )
    else:
      stats["orders_status_updated"] += _sync_crm_orders_delivery_status(
        crm_orders,
        seller=seller,
        scanned_at=None,
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

  result = _apply_wb_supply_scan_index(seller, wb_supplies, client=client)
  detail_scanned, detail_closed = _apply_stuck_supply_detail_scans(
    seller,
    client,
    wb_supplies,
  )
  result["supplies_scanned"] += detail_scanned
  result["orders_closed"] += detail_closed
  result["orders_reopened"] = _revert_premature_supply_scans(
    seller,
    wb_supplies,
    client=client,
  )
  return result


def _revert_premature_supply_scans(
  seller: Seller,
  wb_supplies: list[dict],
  *,
  client=None,
) -> int:
  """Вернуть во «В доставке» поставки, ошибочно закрытые по closedAt без scanDt."""
  wb_by_id = {
    str(item.get("id") or ""): item
    for item in wb_supplies
    if item.get("id")
  }
  reopened = 0
  supplies = Supply.objects.filter(
    seller=seller,
    status=Supply.Status.CONFIRMED,
    wb_scanned_at__isnull=False,
  ).prefetch_related("orders")
  for supply in supplies:
    wb_supply = wb_by_id.get(supply.wb_supply_id)
    if wb_supply is not None and _wb_supply_scanned_at(wb_supply) is not None:
      continue
    if client is not None:
      detail = _fetch_supply_detail_raw(client, supply.wb_supply_id)
      if detail is None:
        continue
      detail_scanned = _wb_supply_scanned_at(detail)
      if detail_scanned:
        orders = list(supply.orders.all())
        _finalize_supply_scan(
          supply,
          orders,
          seller=seller,
          scanned_at=detail_scanned,
        )
        continue
    if wb_supply is None:
      continue
    supply.wb_scanned_at = None
    supply.save(update_fields=["wb_scanned_at", "updated_at"])
    orders_to_reopen = [
      order for order in supply.orders.all()
      if not order_accepted_at_wb_sc(order)
    ]
    reopened += _sync_crm_orders_delivery_status(
      orders_to_reopen,
      seller=seller,
      scanned_at=None,
    )
  return reopened


def _pending_scan_supplies_qs(seller: Seller):
  """Все CRM-поставки без scanDt — без фильтра склада (для sync)."""
  return (
    Supply.objects.filter(
      seller=seller,
      status=Supply.Status.CONFIRMED,
      wb_scanned_at__isnull=True,
    )
    .exclude(wb_supply_id="")
    .order_by("-updated_at")
  )


def _stuck_delivery_supplies_qs(seller: Seller):
  """Поставки на вкладке «В доставке» — те же фильтры, что и в UI."""
  return delivery_stage_supplies_queryset(seller)


def reconcile_stuck_in_delivery_supplies(seller: Seller, client=None) -> dict:
  """
  Найти поставки, застрявшие во «В доставке» из‑за забытого scanDt в CRM,
  и закрыть их, если WB уже принял поставку (есть scanDt).
  """
  if not seller.wb_enabled or not seller.wb_api_token_encrypted:
    return {"skipped": True, "reason": "wb_disabled"}

  if client is None:
    client = _get_client(seller)

  try:
    wb_supplies = client.fetch_supplies()
  except WBApiError as exc:
    raise AssemblyError(str(exc)) from exc

  stuck_ids = set(
    _pending_scan_supplies_qs(seller).values_list("wb_supply_id", flat=True),
  )
  if not stuck_ids:
    return {
      "stuck_supplies": 0,
      "supplies_checked": len(wb_supplies),
      "supplies_scanned": 0,
      "orders_closed": 0,
    }

  scan_by_id = _build_wb_supply_scan_index(wb_supplies)
  relevant_scan = {sid: scan_by_id[sid] for sid in stuck_ids if sid in scan_by_id}
  if not relevant_scan:
    detail_scanned, detail_closed = _apply_stuck_supply_detail_scans(
      seller,
      client,
      wb_supplies,
    )
    return {
      "stuck_supplies": len(stuck_ids),
      "supplies_checked": len(wb_supplies),
      "supplies_scanned": detail_scanned,
      "orders_closed": detail_closed,
    }

  wb_supplies_subset = [
    item for item in wb_supplies if str(item.get("id") or "") in relevant_scan
  ]
  result = _apply_wb_supply_scan_index(
    seller,
    wb_supplies_subset,
    only_supply_ids=stuck_ids,
    client=client,
  )
  result["stuck_supplies"] = len(stuck_ids)
  return result


def reconcile_stuck_in_delivery_all_sellers() -> dict:
  sellers = Seller.objects.filter(is_active=True, wb_enabled=True).exclude(wb_api_token_encrypted="")
  results = []
  errors = []
  totals = {"supplies_scanned": 0, "orders_closed": 0, "stuck_supplies": 0}

  for seller in sellers:
    try:
      stats = reconcile_stuck_in_delivery_supplies(seller)
      results.append({"seller_id": seller.id, **stats})
      totals["supplies_scanned"] += int(stats.get("supplies_scanned") or 0)
      totals["orders_closed"] += int(stats.get("orders_closed") or 0)
      totals["stuck_supplies"] += int(stats.get("stuck_supplies") or 0)
    except AssemblyError as exc:
      errors.append({"seller_id": seller.id, "error": str(exc)})

  return {"results": results, "errors": errors, "totals": totals}


def _apply_wb_supply_scan_index(
  seller: Seller,
  wb_supplies: list[dict],
  *,
  only_supply_ids: set[str] | None = None,
  client=None,
) -> dict:
  scan_by_id = _build_wb_supply_scan_index(wb_supplies)
  if not scan_by_id:
    return {"supplies_checked": len(wb_supplies), "supplies_scanned": 0, "orders_closed": 0}

  target_ids = set(scan_by_id.keys())
  if only_supply_ids is not None:
    target_ids &= only_supply_ids
  if not target_ids:
    return {"supplies_checked": len(wb_supplies), "supplies_scanned": 0, "orders_closed": 0}

  supplies_scanned = 0
  orders_closed = 0

  for wb_supply_id in target_ids:
    scanned_at = scan_by_id.get(wb_supply_id)
    if not scanned_at:
      continue
    closed, counted = _apply_scan_to_crm_supply(
      seller,
      wb_supply_id=wb_supply_id,
      scanned_at=scanned_at,
      client=client,
    )
    if counted:
      supplies_scanned += 1
      orders_closed += closed

  return {
    "supplies_checked": len(wb_supplies),
    "supplies_scanned": supplies_scanned,
    "orders_closed": orders_closed,
  }
