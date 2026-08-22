"""Аналитика кабинета селлера."""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Count
from django.utils import timezone

from apps.orders.models import Order
from apps.sellers.models import Seller
from apps.sellers.services.warehouse_filter import filter_orders_for_seller_cabinet
from apps.warehouse.models import Product

SALES_LOOKBACK_DAYS = 7


def _period_bounds():
  now = timezone.now()
  today = timezone.localdate()
  week_start = today - timedelta(days=6)
  month_start = today.replace(day=1)
  sales_start = now - timedelta(days=SALES_LOOKBACK_DAYS)
  return today, week_start, month_start, sales_start


def _fulfillment_barcodes(seller: Seller) -> set[str]:
  return set(Product.objects.filter(seller=seller).values_list("barcode", flat=True))


def _active_orders_qs(seller: Seller):
  qs = filter_orders_for_seller_cabinet(
    Order.objects.exclude(status=Order.Status.CANCELLED),
    seller,
  )
  barcodes = _fulfillment_barcodes(seller)
  if not barcodes:
    return qs.none()
  return qs.filter(barcode__in=barcodes)


def _order_counts_by_barcode(seller: Seller) -> dict[str, dict[str, int]]:
  today, week_start, month_start, _ = _period_bounds()
  qs = _active_orders_qs(seller)
  result: dict[str, dict[str, int]] = {}

  def bump(barcode: str, key: str, value: int = 1) -> None:
    if not barcode:
      return
    result.setdefault(barcode, {"day": 0, "week": 0, "month": 0})
    result[barcode][key] += value

  for row in qs.filter(created_at__date=today).values("barcode").annotate(c=Count("id")):
    bump(row["barcode"], "day", row["c"])

  for row in qs.filter(created_at__date__gte=week_start).values("barcode").annotate(c=Count("id")):
    bump(row["barcode"], "week", row["c"])

  for row in qs.filter(created_at__date__gte=month_start).values("barcode").annotate(c=Count("id")):
    bump(row["barcode"], "month", row["c"])

  return result


def _avg_daily_sales(seller: Seller, barcode: str, sales_start) -> float:
  count = (
    _active_orders_qs(seller)
    .filter(barcode=barcode, created_at__gte=sales_start)
    .count()
  )
  return round(count / SALES_LOOKBACK_DAYS, 2)


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


def build_seller_summary(seller: Seller) -> dict:
  today, week_start, month_start, _ = _period_bounds()
  qs = _active_orders_qs(seller)
  return {
    "orders_day": qs.filter(created_at__date=today).count(),
    "orders_week": qs.filter(created_at__date__gte=week_start).count(),
    "orders_month": qs.filter(created_at__date__gte=month_start).count(),
    "sku_count": Product.objects.filter(seller=seller, quantity__gt=0).count(),
    "total_stock": sum(
      Product.objects.filter(seller=seller).values_list("quantity", flat=True)
    ),
  }


def build_barcode_analytics(seller: Seller, barcode: str | None = None) -> list[dict]:
  _, _, _, sales_start = _period_bounds()
  order_counts = _order_counts_by_barcode(seller)
  products = Product.objects.filter(seller=seller)
  if barcode:
    products = products.filter(barcode=barcode)

  items: list[dict] = []
  for product in products.order_by("name", "barcode"):
    counts = order_counts.get(product.barcode, {"day": 0, "week": 0, "month": 0})
    avg_daily = _avg_daily_sales(seller, product.barcode, sales_start)
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


def build_barcode_detail(seller: Seller, barcode: str) -> dict | None:
  items = build_barcode_analytics(seller, barcode=barcode)
  if not items:
    return None
  item = items[0]
  _, _, _, sales_start = _period_bounds()
  daily: list[dict] = []
  for offset in range(SALES_LOOKBACK_DAYS - 1, -1, -1):
    day = timezone.localdate() - timedelta(days=offset)
    count = (
      _active_orders_qs(seller)
      .filter(barcode=barcode, created_at__date=day)
      .count()
    )
    daily.append({"date": day.isoformat(), "orders": count})
  item["daily_orders"] = daily
  item["sales_lookback_days"] = SALES_LOOKBACK_DAYS
  return item
