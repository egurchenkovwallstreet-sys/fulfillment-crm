"""Статистика FBS-заказов селлера напрямую из WB API."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from django.utils import timezone

from apps.integrations.wb_client import WBApiError, WBClient, WBOrderData
from apps.integrations.wb_crypto import TokenCryptoError, decrypt_token
from apps.orders.models import Order
from apps.sellers.models import Seller, SellerWarehouse
from apps.sellers.services.calendar_periods import (
  calendar_month_start,
  calendar_week_bounds,
  days_back_to_cover_previous_month,
  previous_month_bounds,
  previous_week_bounds,
  today_local,
)
from apps.sellers.services.warehouse_filter import (
  get_enabled_warehouse_match_ids,
  order_matches_enabled_warehouse,
)

SALES_LOOKBACK_DAYS = 7
WB_FETCH_DAYS_MIN = 30


class SellerAnalyticsError(Exception):
  pass


def _wb_fetch_days() -> int:
  return max(WB_FETCH_DAYS_MIN, days_back_to_cover_previous_month())


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


def _order_local_date(order: WBOrderData) -> date | None:
  if not order.created_at:
    return None
  return timezone.localtime(order.created_at).date()


def _is_fbs_order(order: WBOrderData) -> bool:
  if not order.delivery_type:
    return True
  return order.delivery_type == "fbs"


def _enrich_orders_from_db(seller: Seller, orders: list[WBOrderData]) -> None:
  need_ids = [
    order.wb_order_id
    for order in orders
    if order.warehouse_id is None or order.created_at is None
  ]
  if not need_ids:
    return

  db_map = dict(
    Order.objects.filter(seller=seller, wb_order_id__in=need_ids).values_list(
      "wb_order_id",
      "wb_warehouse_id",
      "wb_created_at",
    )
  )

  for order in orders:
    row = db_map.get(order.wb_order_id)
    if not row:
      continue
    wb_warehouse_id, wb_created_at = row
    if order.warehouse_id is None and wb_warehouse_id is not None:
      order.warehouse_id = wb_warehouse_id
    if order.created_at is None and wb_created_at is not None:
      order.created_at = wb_created_at


def _fetch_wb_fbs_orders(seller: Seller) -> list[WBOrderData]:
  if not seller.wb_api_token_encrypted:
    raise SellerAnalyticsError("Токен WB не настроен для этого селлера")
  try:
    token = decrypt_token(seller.wb_api_token_encrypted)
  except TokenCryptoError as exc:
    raise SellerAnalyticsError("Не удалось расшифровать токен WB") from exc

  match_ids = get_enabled_warehouse_match_ids(seller)
  if not match_ids:
    raise SellerAnalyticsError("Не выбраны обслуживаемые склады WB")

  try:
    client = WBClient(token)
    wb_orders = client.fetch_fbs_orders_for_period(days=_wb_fetch_days()).orders
  except WBApiError as exc:
    raise SellerAnalyticsError(str(exc)) from exc

  _enrich_orders_from_db(seller, wb_orders)

  seen: set[int] = set()
  orders: list[WBOrderData] = []
  for order in wb_orders:
    if order.wb_order_id in seen:
      continue
    seen.add(order.wb_order_id)
    if not _is_fbs_order(order):
      continue
    if not order_matches_enabled_warehouse(
      seller,
      order.warehouse_id,
      order.office_id,
      match_ids=match_ids,
    ):
      continue
    if not order.barcode or not order.created_at:
      continue
    orders.append(order)
  return orders


def get_enabled_warehouses_meta(seller: Seller) -> list[dict]:
  return [
    {
      "wb_warehouse_id": wh.wb_warehouse_id,
      "office_id": wh.office_id,
      "name": wh.name or f"Склад #{wh.wb_warehouse_id}",
    }
    for wh in SellerWarehouse.objects.filter(seller=seller, is_enabled=True).order_by("name")
  ]


def load_wb_fbs_stats(seller: Seller) -> tuple[dict, dict[str, dict[str, int]], dict[str, dict[date, int]]]:
  today = today_local()
  week_start, week_end = calendar_week_bounds(today)
  month_start = calendar_month_start(today)
  yesterday = today - timedelta(days=1)
  prev_week_start, prev_week_end = previous_week_bounds(today)
  prev_month_start, prev_month_end = previous_month_bounds(today)
  sales_start = timezone.now() - timedelta(days=SALES_LOOKBACK_DAYS)
  sales_start_date = timezone.localdate(sales_start)

  counts = {
    "day": 0,
    "day_prev": 0,
    "week": 0,
    "week_prev": 0,
    "month": 0,
    "month_prev": 0,
  }
  by_barcode: dict[str, dict[str, int]] = {}
  daily_by_barcode: dict[str, dict[date, int]] = defaultdict(lambda: defaultdict(int))

  for order in _fetch_wb_fbs_orders(seller):
    order_date = _order_local_date(order)
    if order_date is None:
      continue

    if order_date == today:
      counts["day"] += 1
    if order_date == yesterday:
      counts["day_prev"] += 1
    if week_start <= order_date <= week_end:
      counts["week"] += 1
    if prev_week_start <= order_date <= prev_week_end:
      counts["week_prev"] += 1
    if month_start <= order_date <= today:
      counts["month"] += 1
    if prev_month_start <= order_date <= prev_month_end:
      counts["month_prev"] += 1

    stats = by_barcode.setdefault(order.barcode, {"day": 0, "week": 0, "month": 0})
    if order_date == today:
      stats["day"] += 1
    if week_start <= order_date <= week_end:
      stats["week"] += 1
    if month_start <= order_date <= today:
      stats["month"] += 1
    if order_date >= sales_start_date:
      daily_by_barcode[order.barcode][order_date] += 1

  summary = {
    "orders_day": _period_metric(counts["day"], counts["day_prev"]),
    "orders_week": _period_metric(counts["week"], counts["week_prev"]),
    "orders_month": _period_metric(counts["month"], counts["month_prev"]),
  }
  return summary, by_barcode, daily_by_barcode
