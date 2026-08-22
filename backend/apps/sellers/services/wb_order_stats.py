"""Статистика FBS-заказов селлера напрямую из WB API."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from django.utils import timezone

from apps.integrations.wb_client import WBApiError, WBClient, WBOrderData
from apps.integrations.wb_crypto import TokenCryptoError, decrypt_token
from apps.sellers.models import Seller
from apps.sellers.services.warehouse_filter import get_enabled_wb_warehouse_ids

SALES_LOOKBACK_DAYS = 7
WB_FETCH_DAYS = 31


class SellerAnalyticsError(Exception):
  pass


def _period_bounds():
  now = timezone.now()
  today = timezone.localdate()
  week_start = today - timedelta(days=6)
  month_start = today.replace(day=1)
  sales_start = now - timedelta(days=SALES_LOOKBACK_DAYS)
  return today, week_start, month_start, sales_start


def _order_local_date(order: WBOrderData) -> date | None:
  if not order.created_at:
    return None
  return timezone.localtime(order.created_at).date()


def _fetch_wb_fbs_orders(seller: Seller) -> list[WBOrderData]:
  if not seller.wb_api_token_encrypted:
    raise SellerAnalyticsError("Токен WB не настроен для этого селлера")
  try:
    token = decrypt_token(seller.wb_api_token_encrypted)
  except TokenCryptoError as exc:
    raise SellerAnalyticsError("Не удалось расшифровать токен WB") from exc

  enabled = get_enabled_wb_warehouse_ids(seller)
  if not enabled:
    raise SellerAnalyticsError("Не выбраны обслуживаемые склады WB")

  try:
    client = WBClient(token)
    result = client.fetch_recent_orders(days=WB_FETCH_DAYS)
  except WBApiError as exc:
    raise SellerAnalyticsError(str(exc)) from exc

  seen: set[int] = set()
  orders: list[WBOrderData] = []
  for order in result.orders:
    if order.wb_order_id in seen:
      continue
    seen.add(order.wb_order_id)
    if order.warehouse_id is None or order.warehouse_id not in enabled:
      continue
    if not order.barcode or not order.created_at:
      continue
    orders.append(order)
  return orders


def load_wb_fbs_stats(seller: Seller) -> tuple[dict[str, int], dict[str, dict[str, int]], dict[str, dict[date, int]]]:
  """
  Возвращает:
  - summary: orders_day/week/month
  - by_barcode: {barcode: {day, week, month}}
  - daily_by_barcode: {barcode: {date: count}} за SALES_LOOKBACK_DAYS
  """
  today, week_start, month_start, sales_start = _period_bounds()
  sales_start_date = timezone.localdate(sales_start)

  summary = {"orders_day": 0, "orders_week": 0, "orders_month": 0}
  by_barcode: dict[str, dict[str, int]] = {}
  daily_by_barcode: dict[str, dict[date, int]] = defaultdict(lambda: defaultdict(int))

  for order in _fetch_wb_fbs_orders(seller):
    order_date = _order_local_date(order)
    if order_date is None:
      continue

    if order_date == today:
      summary["orders_day"] += 1
    if order_date >= week_start:
      summary["orders_week"] += 1
    if order_date >= month_start:
      summary["orders_month"] += 1

    stats = by_barcode.setdefault(order.barcode, {"day": 0, "week": 0, "month": 0})
    if order_date == today:
      stats["day"] += 1
    if order_date >= week_start:
      stats["week"] += 1
    if order_date >= month_start:
      stats["month"] += 1
    if order_date >= sales_start_date:
      daily_by_barcode[order.barcode][order_date] += 1

  return summary, by_barcode, daily_by_barcode
