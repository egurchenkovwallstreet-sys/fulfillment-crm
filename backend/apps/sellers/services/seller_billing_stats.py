"""Отгрузки FBS — по факту передачи поставки на склад WB."""
from __future__ import annotations

import re
import time
from collections import defaultdict
from datetime import date, datetime, timedelta

from django.utils import timezone

from apps.integrations.wb_client import REQUEST_INTERVAL_SEC, WBApiError, WBClient
from apps.integrations.wb_crypto import TokenCryptoError, decrypt_token
from apps.orders.models import Order, Supply
from apps.orders.services.supply_sync import _parse_wb_datetime
from apps.sellers.models import Seller
from apps.sellers.services.calendar_periods import (
  calendar_week_bounds,
  calendar_week_bounds_offset,
  iter_week_days,
  today_local,
)
from apps.sellers.services.warehouse_filter import filter_orders_for_seller
from apps.sellers.services.wb_order_stats import SellerAnalyticsError

CRM_SUPPLY_NAME_RE = re.compile(r"^CRM-(\d+)-")
MAX_SUPPLY_ORDER_FETCHES = 80
SHIPMENTS_WEEKS_HISTORY = 4


def _get_client(seller: Seller) -> WBClient:
  if not seller.wb_api_token_encrypted:
    raise SellerAnalyticsError("Токен WB не настроен для этого селлера")
  try:
    token = decrypt_token(seller.wb_api_token_encrypted)
  except TokenCryptoError as exc:
    raise SellerAnalyticsError("Не удалось расшифровать токен WB") from exc
  return WBClient(token)


def _supply_handoff_at(wb_supply: dict) -> datetime | None:
  for key in ("scanDt", "scan_dt", "closedAt", "closed_at"):
    parsed = _parse_wb_datetime(wb_supply.get(key))
    if parsed is not None:
      return parsed
  return None


def _order_ids_from_crm_supply(supply: Supply) -> list[int]:
  return list(supply.orders.values_list("wb_order_id", flat=True))


def _order_ids_from_wb_supply_name(name: str) -> list[int]:
  match = CRM_SUPPLY_NAME_RE.match(name or "")
  if not match:
    return []
  return [int(match.group(1))]


def _eligible_order_count(seller: Seller, wb_order_ids: list[int]) -> int:
  if not wb_order_ids:
    return 0
  return (
    filter_orders_for_seller(
      Order.objects.filter(seller=seller, wb_order_id__in=wb_order_ids),
      seller,
    ).count()
  )


def _week_start_for(day: date) -> date:
  return day - timedelta(days=day.weekday())


def _build_week_payload(
  week_start: date,
  week_end: date,
  *,
  daily_counts: dict[date, int],
  supplies_per_week: dict[date, int],
  today: date,
) -> dict:
  days = [
    {
      "date": day.isoformat(),
      "weekday": label,
      "orders": daily_counts.get(day, 0),
    }
    for day, label in iter_week_days(week_start)
  ]
  return {
    "week_start": week_start.isoformat(),
    "week_end": week_end.isoformat(),
    "total": sum(day["orders"] for day in days),
    "supplies_count": supplies_per_week.get(week_start, 0),
    "is_current": week_start <= today <= week_end,
    "days": days,
  }


def load_weekly_shipped_orders(seller: Seller, *, weeks: int = SHIPMENTS_WEEKS_HISTORY) -> dict:
  """
  Заказы, переданные на склад WB по календарным неделям (пн–вс, МСК).
  Источник: GET /api/v3/supplies, done=true, дата scanDt/closedAt.
  """
  today = today_local()
  current_week_start, current_week_end = calendar_week_bounds(today)
  oldest_week_start, _ = calendar_week_bounds_offset(weeks - 1, today)

  daily_counts: dict[date, int] = defaultdict(int)
  supplies_per_week: dict[date, int] = defaultdict(int)

  client = _get_client(seller)
  try:
    wb_supplies = client.fetch_supplies()
  except WBApiError as exc:
    raise SellerAnalyticsError(str(exc)) from exc

  crm_supplies = {
    supply.wb_supply_id: supply
    for supply in Supply.objects.filter(seller=seller).exclude(wb_supply_id="").prefetch_related("orders")
  }

  api_fetches = 0

  for wb_supply in wb_supplies:
    if not wb_supply.get("done"):
      continue

    handoff_at = _supply_handoff_at(wb_supply)
    if handoff_at is None:
      continue

    handoff_date = timezone.localtime(handoff_at).date()
    if not (oldest_week_start <= handoff_date <= current_week_end):
      continue

    wb_supply_id = str(wb_supply.get("id") or "")
    if not wb_supply_id:
      continue

    name = str(wb_supply.get("name") or "")
    order_wb_ids: list[int] = []

    crm_supply = crm_supplies.get(wb_supply_id)
    if crm_supply is not None:
      order_wb_ids = _order_ids_from_crm_supply(crm_supply)
    else:
      order_wb_ids = _order_ids_from_wb_supply_name(name)
      if not order_wb_ids and api_fetches < MAX_SUPPLY_ORDER_FETCHES:
        try:
          order_wb_ids = client.fetch_supply_order_ids(wb_supply_id)
          api_fetches += 1
          time.sleep(REQUEST_INTERVAL_SEC)
        except WBApiError:
          order_wb_ids = []

    order_count = _eligible_order_count(seller, order_wb_ids)
    if order_count <= 0:
      continue

    daily_counts[handoff_date] += order_count
    supplies_per_week[_week_start_for(handoff_date)] += 1

  weeks_data = [
    _build_week_payload(
      *calendar_week_bounds_offset(weeks_ago, today),
      daily_counts=daily_counts,
      supplies_per_week=supplies_per_week,
      today=today,
    )
    for weeks_ago in range(weeks)
  ]

  return {
    "today": today.isoformat(),
    "weeks": weeks_data,
  }
