"""Аналитика кабинета селлера."""
from __future__ import annotations

import logging
from datetime import timedelta

from django.utils import timezone

from apps.orders.services.assembly import get_seller_wb_tab_counts
from apps.sellers.models import Seller
from apps.sellers.services.calendar_periods import calendar_week_bounds_offset, iter_week_days, today_local
from apps.sellers.services.seller_billing_stats import load_weekly_shipped_orders
from apps.sellers.services.wb_order_stats import (
  SALES_LOOKBACK_DAYS,
  SellerAnalyticsError,
  load_wb_fbs_stats,
)
from apps.warehouse.models import Product

logger = logging.getLogger(__name__)


def _empty_weekly_shipments(weeks: int = 4) -> dict:
  today = today_local()
  weeks_data = []
  for weeks_ago in range(weeks):
    week_start, week_end = calendar_week_bounds_offset(weeks_ago, today)
    weeks_data.append({
      "week_start": week_start.isoformat(),
      "week_end": week_end.isoformat(),
      "total": 0,
      "total_amount": "0.00",
      "supplies_count": 0,
      "is_current": weeks_ago == 0,
      "days": [
        {"date": day.isoformat(), "weekday": label, "orders": 0, "amount": "0.00"}
        for day, label in iter_week_days(week_start)
      ],
    })
  return {
    "today": today.isoformat(),
    "weeks": weeks_data,
  }


def _stock_level(days_remaining: float | None, quantity: int) -> str:
  if quantity <= 0:
    return "critical"
  if days_remaining is None:
    return "excess"
  if days_remaining < 5:
    return "critical"
  if days_remaining <= 15:
    return "sufficient"
  return "excess"


def _days_remaining(quantity: int, avg_daily: float) -> float | None:
  if quantity <= 0:
    return 0.0
  if avg_daily <= 0:
    return None
  return round(quantity / avg_daily, 1)


def _build_items(
  seller: Seller,
  order_counts: dict[str, dict[str, int]],
  daily_by_barcode: dict,
  *,
  barcode: str | None = None,
) -> list[dict]:
  products = Product.objects.filter(seller=seller)
  if barcode:
    products = products.filter(barcode=barcode)

  items: list[dict] = []
  for product in products.order_by("name", "barcode"):
    counts = order_counts.get(product.barcode, {"day": 0, "week": 0, "month": 0})
    week_orders = sum(daily_by_barcode.get(product.barcode, {}).values())
    avg_daily = round(week_orders / SALES_LOOKBACK_DAYS, 2)
    days = _days_remaining(product.quantity, avg_daily)
    level = _stock_level(days, product.quantity)
    items.append({
      "barcode": product.barcode,
      "name": product.name or product.barcode,
      "stock_quantity": product.quantity,
      "orders_day": counts["day"],
      "orders_week": counts["week"],
      "orders_month": counts["month"],
      "avg_daily_sales": avg_daily,
      "days_remaining": days,
      "stock_level": level,
    })

  level_order = {"critical": 0, "sufficient": 1, "excess": 2, "unknown": 3}
  items.sort(key=lambda row: (level_order.get(row["stock_level"], 9), row["days_remaining"] if row["days_remaining"] is not None else 9999))
  return items


def build_seller_cabinet_payload(seller: Seller) -> tuple[dict, list[dict], dict, dict]:
  order_summary, order_counts, daily_by_barcode = load_wb_fbs_stats(seller)
  summary = {
    **order_summary,
    "sku_count": Product.objects.filter(seller=seller, quantity__gt=0).count(),
    "total_stock": sum(
      Product.objects.filter(seller=seller).values_list("quantity", flat=True)
    ),
  }
  items = _build_items(seller, order_counts, daily_by_barcode)
  wb_stages = get_seller_wb_tab_counts(seller)
  try:
    weekly_shipments = load_weekly_shipped_orders(seller)
  except SellerAnalyticsError as exc:
    logger.warning("weekly shipments unavailable for seller %s: %s", seller.id, exc)
    weekly_shipments = _empty_weekly_shipments()
  return summary, items, wb_stages, weekly_shipments


def build_seller_summary(seller: Seller) -> dict:
  summary, _, _, _ = build_seller_cabinet_payload(seller)
  return summary


def build_barcode_analytics(seller: Seller, barcode: str | None = None) -> list[dict]:
  _, order_counts, daily_by_barcode, _ = _load_cabinet_order_stats(seller)
  return _build_items(seller, order_counts, daily_by_barcode, barcode=barcode)


def _load_cabinet_order_stats(seller: Seller) -> tuple[dict, dict, dict, dict]:
  order_summary, order_counts, daily_by_barcode = load_wb_fbs_stats(seller)
  return order_summary, order_counts, daily_by_barcode, {}


def build_barcode_detail(seller: Seller, barcode: str) -> dict | None:
  _, order_counts, daily_by_barcode, _ = _load_cabinet_order_stats(seller)
  items = _build_items(seller, order_counts, daily_by_barcode, barcode=barcode)
  if not items:
    return None
  item = items[0]
  daily_map = daily_by_barcode.get(barcode, {})
  daily: list[dict] = []
  for offset in range(SALES_LOOKBACK_DAYS - 1, -1, -1):
    day = timezone.localdate() - timedelta(days=offset)
    daily.append({"date": day.isoformat(), "orders": daily_map.get(day, 0)})
  item["daily_orders"] = daily
  item["sales_lookback_days"] = SALES_LOOKBACK_DAYS
  return item
