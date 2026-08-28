"""Аналитика кабинета селлера."""
from __future__ import annotations

import logging
from datetime import timedelta

from django.utils import timezone

from apps.integrations.marketplace import OZON, WB, normalize_marketplace
from apps.orders.models import OzonPosting
from apps.orders.services.assembly import get_seller_wb_tab_counts
from apps.sellers.models import Seller
from apps.sellers.services.calendar_periods import calendar_week_bounds_offset, iter_week_days, today_local
from apps.sellers.services.ozon_billing_stats import load_weekly_ozon_shipped_orders
from apps.sellers.services.ozon_order_stats import get_enabled_ozon_warehouses_meta, load_ozon_fbs_stats
from apps.sellers.services.seller_billing_stats import load_weekly_shipped_orders
from apps.sellers.services.wb_order_stats import (
  SALES_LOOKBACK_DAYS,
  SellerAnalyticsError,
  get_enabled_warehouses_meta,
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
    return "urgent"
  if days_remaining is None:
    return "excess"
  if days_remaining < 5:
    return "urgent"
  if days_remaining < 10:
    return "restock"
  if days_remaining <= 20:
    return "sufficient"
  return "excess"


def _days_remaining(quantity: int, avg_daily: float) -> float | None:
  if quantity <= 0:
    return 0.0
  if avg_daily <= 0:
    return None
  return round(quantity / avg_daily, 1)


def _product_queryset(seller: Seller, marketplace: str):
  qs = Product.objects.filter(seller=seller)
  mp = normalize_marketplace(marketplace)
  if mp == OZON:
    return qs.filter(marketplace=OZON)
  return qs.filter(marketplace=WB)


def _build_items(
  seller: Seller,
  order_counts: dict[str, dict[str, int]],
  daily_by_barcode: dict,
  *,
  marketplace: str = WB,
  barcode: str | None = None,
) -> list[dict]:
  products = _product_queryset(seller, marketplace)
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
      "tech_size": (product.tech_size or "").strip(),
      "photo_url": (product.photo_url or "").strip(),
      "stock_quantity": product.quantity,
      "orders_day": counts["day"],
      "orders_week": counts["week"],
      "orders_month": counts["month"],
      "avg_daily_sales": avg_daily,
      "days_remaining": days,
      "stock_level": level,
    })

  level_order = {"urgent": 0, "restock": 1, "sufficient": 2, "excess": 3, "unknown": 4}
  items.sort(key=lambda row: (level_order.get(row["stock_level"], 9), row["days_remaining"] if row["days_remaining"] is not None else 9999))
  return items


def _ozon_stage_counts(seller: Seller) -> dict[str, int]:
  return {
    "new": OzonPosting.objects.filter(
      seller=seller,
      crm_stage=OzonPosting.CrmStage.NEW,
      ozon_status="awaiting_packaging",
    ).count(),
    "in_picking": OzonPosting.objects.filter(
      seller=seller,
      crm_stage=OzonPosting.CrmStage.IN_PICKING,
    ).count(),
    "in_delivery": OzonPosting.objects.filter(
      seller=seller,
      crm_stage=OzonPosting.CrmStage.IN_DELIVERY,
    ).count(),
  }


def build_seller_cabinet_payload(seller: Seller, *, marketplace: str = WB) -> tuple[dict, list[dict], dict, dict, dict]:
  mp = normalize_marketplace(marketplace)
  if mp == OZON:
    order_summary, order_counts, daily_by_barcode = load_ozon_fbs_stats(seller)
    products_qs = _product_queryset(seller, OZON)
    stages = _ozon_stage_counts(seller)
    weekly_loader = load_weekly_ozon_shipped_orders
    meta = {
      "enabled_warehouses": get_enabled_ozon_warehouses_meta(seller),
      "source": "ozon_fbs_api",
      "timezone": "Europe/Moscow",
      "marketplace": OZON,
    }
  else:
    order_summary, order_counts, daily_by_barcode = load_wb_fbs_stats(seller)
    products_qs = _product_queryset(seller, WB)
    stages = get_seller_wb_tab_counts(seller)
    weekly_loader = load_weekly_shipped_orders
    meta = {
      "enabled_warehouses": get_enabled_warehouses_meta(seller),
      "source": "wb_statistics_api",
      "timezone": "Europe/Moscow",
      "marketplace": WB,
    }

  summary = {
    **order_summary,
    "sku_count": products_qs.filter(quantity__gt=0).count(),
    "total_stock": sum(products_qs.values_list("quantity", flat=True)),
  }
  items = _build_items(seller, order_counts, daily_by_barcode, marketplace=mp)
  try:
    weekly_shipments = weekly_loader(seller)
  except SellerAnalyticsError as exc:
    logger.warning("weekly shipments unavailable for seller %s (%s): %s", seller.id, mp, exc)
    weekly_shipments = _empty_weekly_shipments()
  return summary, items, stages, weekly_shipments, meta


def build_seller_summary(seller: Seller, *, marketplace: str = WB) -> dict:
  summary, _, _, _, _ = build_seller_cabinet_payload(seller, marketplace=marketplace)
  return summary


def build_barcode_analytics(seller: Seller, barcode: str | None = None, *, marketplace: str = WB) -> list[dict]:
  _, order_counts, daily_by_barcode, _ = _load_cabinet_order_stats(seller, marketplace=marketplace)
  return _build_items(seller, order_counts, daily_by_barcode, marketplace=marketplace, barcode=barcode)


def _load_cabinet_order_stats(seller: Seller, *, marketplace: str = WB) -> tuple[dict, dict, dict, dict]:
  mp = normalize_marketplace(marketplace)
  if mp == OZON:
    order_summary, order_counts, daily_by_barcode = load_ozon_fbs_stats(seller)
  else:
    order_summary, order_counts, daily_by_barcode = load_wb_fbs_stats(seller)
  return order_summary, order_counts, daily_by_barcode, {}


def build_barcode_detail(seller: Seller, barcode: str, *, marketplace: str = WB) -> dict | None:
  _, order_counts, daily_by_barcode, _ = _load_cabinet_order_stats(seller, marketplace=marketplace)
  items = _build_items(seller, order_counts, daily_by_barcode, marketplace=marketplace, barcode=barcode)
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
