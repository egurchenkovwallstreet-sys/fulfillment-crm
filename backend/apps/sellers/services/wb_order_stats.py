"""Статистика FBS-заказов селлера — Statistics API WB (как сводный отчёт в ЛК)."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from django.utils import timezone

from apps.integrations.wb_client import WBApiError
from apps.integrations.wb_crypto import TokenCryptoError, decrypt_token
from apps.integrations.wb_statistics_client import (
  WBStatisticsClient,
  is_fbs_statistics_row,
  parse_statistics_order_date,
)
from apps.sellers.models import Seller, SellerWarehouse
from apps.sellers.services.calendar_periods import (
  calendar_month_start,
  calendar_week_bounds,
  days_back_to_cover_previous_month,
  previous_month_bounds,
  today_local,
)
from apps.sellers.services.warehouse_filter import seller_has_warehouse_config

SALES_LOOKBACK_DAYS = 7


class SellerAnalyticsError(Exception):
  pass


def _period_metric(current: int, previous: int) -> dict:
  if previous == 0:
    if current == 0:
      direction = "flat"
      change_pct = 0.0
    else:
      direction = "new"
      change_pct = None
  else:
    change_pct = round((current - previous) / previous * 100, 1)
    if change_pct > 0:
      direction = "up"
    elif change_pct < 0:
      direction = "down"
    else:
      direction = "flat"
  return {
    "current": current,
    "previous": previous,
    "change_pct": change_pct,
    "direction": direction,
  }


def _get_statistics_client(seller: Seller) -> WBStatisticsClient:
  if not seller.wb_api_token_encrypted:
    raise SellerAnalyticsError("Токен WB не настроен для этого селлера")
  try:
    token = decrypt_token(seller.wb_api_token_encrypted)
  except TokenCryptoError as exc:
    raise SellerAnalyticsError("Не удалось расшифровать токен WB") from exc
  return WBStatisticsClient(token)


def _enabled_warehouse_names(seller: Seller) -> list[str]:
  return [
    (name or "").strip().lower()
    for name in SellerWarehouse.objects.filter(seller=seller, is_enabled=True).values_list("name", flat=True)
    if (name or "").strip()
  ]


def _statistics_row_matches_enabled_warehouse(seller: Seller, row: dict, *, enabled_names: list[str]) -> bool:
  if not seller_has_warehouse_config(seller):
    return True
  warehouse_name = (row.get("warehouseName") or "").strip().lower()
  if not warehouse_name:
    return False
  for name in enabled_names:
    if name in warehouse_name or warehouse_name in name:
      return True
  return False


def _order_identity(row: dict) -> str:
  srid = (row.get("srid") or "").strip()
  if srid:
    return srid
  g_number = (row.get("gNumber") or "").strip()
  if g_number:
    return g_number
  return ""


def _fetch_statistics_orders(seller: Seller, date_from: date) -> list[dict]:
  client = _get_statistics_client(seller)
  date_from_param = f"{date_from.isoformat()}T00:00:00"
  try:
    return list(client.iter_supplier_orders(date_from_param))
  except WBApiError as exc:
    if exc.status_code == 401:
      raise SellerAnalyticsError(
        "Токен WB не имеет доступа к Statistics API. "
        "Включите категорию «Статистика» при создании токена."
      ) from exc
    raise SellerAnalyticsError(str(exc)) from exc


def load_wb_fbs_stats(seller: Seller) -> tuple[dict, dict[str, dict[str, int]], dict[str, dict[date, int]]]:
  """
  Счётчики заказов как в сводном отчёте WB («Количество заказов»).
  Источник: GET /api/v1/supplier/orders, уникальные srid, FBS (склад продавца).
  """
  today = today_local()
  week_start, week_end = calendar_week_bounds(today)
  month_start = calendar_month_start(today)
  yesterday = today - timedelta(days=1)
  prev_week_start, prev_week_end = previous_week_bounds(today)
  prev_month_start, prev_month_end = previous_month_bounds(today)
  sales_start_date = today - timedelta(days=SALES_LOOKBACK_DAYS - 1)

  fetch_from = previous_month_bounds(today)[0]
  enabled_names = _enabled_warehouse_names(seller)
  rows = _fetch_statistics_orders(seller, fetch_from)

  period_srids: dict[str, set[str]] = {
    "day": set(),
    "day_prev": set(),
    "week": set(),
    "week_prev": set(),
    "month": set(),
    "month_prev": set(),
  }
  barcode_period_srids: dict[str, dict[str, set[str]]] = defaultdict(
    lambda: {"day": set(), "week": set(), "month": set()},
  )
  daily_by_barcode: dict[str, dict[date, int]] = defaultdict(lambda: defaultdict(int))

  for row in rows:
    if not is_fbs_statistics_row(row):
      continue
    if row.get("isCancel"):
      continue
    if not _statistics_row_matches_enabled_warehouse(seller, row, enabled_names=enabled_names):
      continue

    order_dt = parse_statistics_order_date(row.get("date"))
    if order_dt is None:
      continue
    order_date = timezone.localtime(order_dt).date()
    identity = _order_identity(row)
    if not identity:
      continue

    barcode = str(row.get("barcode") or "").strip()

    if order_date == today:
      period_srids["day"].add(identity)
      if barcode:
        barcode_period_srids[barcode]["day"].add(identity)
    if order_date == yesterday:
      period_srids["day_prev"].add(identity)
    if week_start <= order_date <= week_end:
      period_srids["week"].add(identity)
      if barcode:
        barcode_period_srids[barcode]["week"].add(identity)
    if prev_week_start <= order_date <= prev_week_end:
      period_srids["week_prev"].add(identity)
    if month_start <= order_date <= today:
      period_srids["month"].add(identity)
      if barcode:
        barcode_period_srids[barcode]["month"].add(identity)
    if prev_month_start <= order_date <= prev_month_end:
      period_srids["month_prev"].add(identity)
    if barcode and order_date >= sales_start_date:
      daily_by_barcode[barcode][order_date] += 1

  by_barcode = {
    barcode: {
      "day": len(stats["day"]),
      "week": len(stats["week"]),
      "month": len(stats["month"]),
    }
    for barcode, stats in barcode_period_srids.items()
  }

  summary = {
    "orders_day": _period_metric(len(period_srids["day"]), len(period_srids["day_prev"])),
    "orders_week": _period_metric(len(period_srids["week"]), len(period_srids["week_prev"])),
    "orders_month": _period_metric(len(period_srids["month"]), len(period_srids["month_prev"])),
  }
  return summary, by_barcode, daily_by_barcode


def get_enabled_warehouses_meta(seller: Seller) -> list[dict]:
  return [
    {
      "wb_warehouse_id": wh.wb_warehouse_id,
      "office_id": wh.office_id,
      "name": wh.name or f"Склад #{wh.wb_warehouse_id}",
    }
    for wh in SellerWarehouse.objects.filter(seller=seller, is_enabled=True).order_by("name")
  ]
