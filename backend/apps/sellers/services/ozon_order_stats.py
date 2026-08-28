"""Статистика FBS-отправлений Ozon для кабинета селлера."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from django.utils import timezone

from apps.integrations.ozon_client import OzonApiError
from apps.orders.services.ozon_counts import OzonCountsError, ozon_client_for_seller
from apps.orders.services.ozon_postings import _parse_dt
from apps.sellers.models import Seller, SellerOzonWarehouse
from apps.sellers.services.calendar_periods import (
  calendar_month_start,
  calendar_week_bounds,
  previous_month_bounds,
  previous_week_bounds,
  today_local,
)
from apps.sellers.services.wb_order_stats import SALES_LOOKBACK_DAYS, SellerAnalyticsError, _period_metric

OZON_STATS_LOOKBACK_DAYS = 30


def _posting_identity(raw: dict) -> str:
  return str(raw.get("posting_number") or "").strip()


def _posting_barcode(raw: dict) -> str:
  for product_raw in raw.get("products") or []:
    if not isinstance(product_raw, dict):
      continue
    barcode = str(product_raw.get("barcode") or product_raw.get("offer_id") or "").strip()
    if barcode:
      return barcode
  return ""


def _posting_date(raw: dict) -> date | None:
  dt = _parse_dt(raw.get("in_process_at"))
  if dt is None:
    return None
  return timezone.localtime(dt).date()


def get_enabled_ozon_warehouses_meta(seller: Seller) -> list[dict]:
  return [
    {
      "ozon_warehouse_id": wh.ozon_warehouse_id,
      "name": wh.name or f"Склад #{wh.ozon_warehouse_id}",
    }
    for wh in SellerOzonWarehouse.objects.filter(seller=seller, is_enabled=True).order_by("name")
  ]


def load_ozon_fbs_stats(
  seller: Seller,
) -> tuple[dict, dict[str, dict[str, int]], dict[str, dict[date, int]]]:
  """
  Счётчики отправлений Ozon FBS по календарным периодам.
  Источник: /v4/posting/fbs/list за последние 30 дней.
  """
  today = today_local()
  week_start, week_end = calendar_week_bounds(today)
  month_start = calendar_month_start(today)
  yesterday = today - timedelta(days=1)
  prev_week_start, prev_week_end = previous_week_bounds(today)
  prev_month_start, prev_month_end = previous_month_bounds(today)
  sales_start_date = today - timedelta(days=SALES_LOOKBACK_DAYS - 1)

  try:
    client = ozon_client_for_seller(seller)
    rows = client.list_recent_postings(days=OZON_STATS_LOOKBACK_DAYS)
  except (OzonCountsError, OzonApiError) as exc:
    raise SellerAnalyticsError(str(exc)) from exc

  period_ids: dict[str, set[str]] = {
    "day": set(),
    "day_prev": set(),
    "week": set(),
    "week_prev": set(),
    "month": set(),
    "month_prev": set(),
  }
  barcode_period_ids: dict[str, dict[str, set[str]]] = defaultdict(
    lambda: {"day": set(), "week": set(), "month": set()},
  )
  daily_by_barcode: dict[str, dict[date, int]] = defaultdict(lambda: defaultdict(int))

  for row in rows:
    status = str(row.get("status") or "").strip().lower()
    if status in {"cancelled", "canceled"}:
      continue
    order_date = _posting_date(row)
    if order_date is None:
      continue
    identity = _posting_identity(row)
    if not identity:
      continue
    barcode = _posting_barcode(row)

    if order_date == today:
      period_ids["day"].add(identity)
      if barcode:
        barcode_period_ids[barcode]["day"].add(identity)
    if order_date == yesterday:
      period_ids["day_prev"].add(identity)
    if week_start <= order_date <= week_end:
      period_ids["week"].add(identity)
      if barcode:
        barcode_period_ids[barcode]["week"].add(identity)
    if prev_week_start <= order_date <= prev_week_end:
      period_ids["week_prev"].add(identity)
    if month_start <= order_date <= today:
      period_ids["month"].add(identity)
      if barcode:
        barcode_period_ids[barcode]["month"].add(identity)
    if prev_month_start <= order_date <= prev_month_end:
      period_ids["month_prev"].add(identity)
    if barcode and order_date >= sales_start_date:
      daily_by_barcode[barcode][order_date] += 1

  by_barcode = {
    barcode: {
      "day": len(stats["day"]),
      "week": len(stats["week"]),
      "month": len(stats["month"]),
    }
    for barcode, stats in barcode_period_ids.items()
  }
  summary = {
    "orders_day": _period_metric(len(period_ids["day"]), len(period_ids["day_prev"])),
    "orders_week": _period_metric(len(period_ids["week"]), len(period_ids["week_prev"])),
    "orders_month": _period_metric(len(period_ids["month"]), len(period_ids["month_prev"])),
  }
  return summary, by_barcode, daily_by_barcode
