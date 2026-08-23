"""Отгрузки FBS за календарную неделю — по факту передачи поставки на склад WB."""
from __future__ import annotations

import re
import time
from collections import defaultdict
from datetime import date, datetime

from django.utils import timezone

from apps.integrations.wb_client import REQUEST_INTERVAL_SEC, WBApiError, WBClient
from apps.integrations.wb_crypto import TokenCryptoError, decrypt_token
from apps.orders.models import Order, Supply
from apps.orders.services.supply_sync import _parse_wb_datetime
from apps.sellers.models import Seller
from apps.sellers.services.calendar_periods import calendar_week_bounds, iter_week_days, today_local
from apps.sellers.services.warehouse_filter import filter_orders_for_seller
from apps.sellers.services.wb_order_stats import SellerAnalyticsError

CRM_SUPPLY_NAME_RE = re.compile(r"^CRM-(\d+)-")
MAX_SUPPLY_ORDER_FETCHES = 80


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


def load_weekly_shipped_orders(seller: Seller) -> dict:
  """
  Заказы, переданные на склад WB в текущую календарную неделю (пн–вс, МСК).
  Источник: GET /api/v3/supplies, done=true, дата scanDt/closedAt.
  """
  week_start, week_end = calendar_week_bounds()
  daily_counts: dict[date, int] = defaultdict(int)

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
  supplies_in_week = 0

  for wb_supply in wb_supplies:
    if not wb_supply.get("done"):
      continue

    handoff_at = _supply_handoff_at(wb_supply)
    if handoff_at is None:
      continue

    handoff_date = timezone.localtime(handoff_at).date()
    if not (week_start <= handoff_date <= week_end):
      continue

    wb_supply_id = str(wb_supply.get("id") or "")
    if not wb_supply_id:
      continue

    supplies_in_week += 1
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

    daily_counts[handoff_date] += _eligible_order_count(seller, order_wb_ids)

  days = [
    {
      "date": day.isoformat(),
      "weekday": label,
      "orders": daily_counts.get(day, 0),
    }
    for day, label in iter_week_days(week_start)
  ]
  total = sum(day["orders"] for day in days)

  return {
    "week_start": week_start.isoformat(),
    "week_end": week_end.isoformat(),
    "today": today_local().isoformat(),
    "total": total,
    "supplies_count": supplies_in_week,
    "days": days,
  }
