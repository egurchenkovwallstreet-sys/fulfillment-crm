"""Отгрузки по товарам из данных CRM (без внешних API)."""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from django.utils import timezone

from apps.integrations.marketplace import OZON, WB, normalize_marketplace
from apps.orders.models import Order, OzonPosting
from apps.sellers.models import Seller
from apps.sellers.services.calendar_periods import (
  calendar_month_start,
  calendar_week_bounds,
  today_local,
)
from apps.warehouse.models import Product

PERIOD_DAY = "day"
PERIOD_WEEK = "week"
PERIOD_MONTH = "month"
PERIOD_ALL = "all"
PERIOD_CUSTOM = "custom"
PERIOD_CHOICES = {PERIOD_DAY, PERIOD_WEEK, PERIOD_MONTH, PERIOD_ALL, PERIOD_CUSTOM}


def resolve_stats_period(
  *,
  period: str,
  date_from: date | None = None,
  date_to: date | None = None,
) -> tuple[date | None, date | None, str]:
  today = today_local()
  preset = period if period in PERIOD_CHOICES else PERIOD_ALL

  if preset == PERIOD_CUSTOM:
    if date_from and date_to and date_from > date_to:
      date_from, date_to = date_to, date_from
    return date_from, date_to, preset

  if preset == PERIOD_DAY:
    return today, today, preset
  if preset == PERIOD_WEEK:
    start, end = calendar_week_bounds(today)
    return start, end, preset
  if preset == PERIOD_MONTH:
    return calendar_month_start(today), today, preset
  return None, None, PERIOD_ALL


def _wb_shipped_qs(seller: Seller):
  return Order.objects.filter(
    seller=seller,
    in_delivery_at__isnull=False,
  ).exclude(barcode="")


def _ozon_shipped_qs(seller: Seller):
  return OzonPosting.objects.filter(
    seller=seller,
    shipped_at__isnull=False,
  ).exclude(barcode="")


def _crm_bounds(seller: Seller, *, marketplace: str) -> tuple[date | None, date | None]:
  mp = normalize_marketplace(marketplace)
  if mp == OZON:
    qs = _ozon_shipped_qs(seller)
    date_field = "shipped_at"
  else:
    qs = _wb_shipped_qs(seller)
    date_field = "in_delivery_at"

  first = qs.order_by(date_field).values_list(date_field, flat=True).first()
  last = qs.order_by(f"-{date_field}").values_list(date_field, flat=True).first()
  if not first or not last:
    return None, None
  return timezone.localtime(first).date(), timezone.localtime(last).date()


def _apply_date_filter(qs, *, field: str, date_from: date | None, date_to: date | None):
  if date_from:
    qs = qs.filter(**{f"{field}__date__gte": date_from})
  if date_to:
    qs = qs.filter(**{f"{field}__date__lte": date_to})
  return qs


def _aggregate_wb(seller: Seller, *, date_from: date | None, date_to: date | None, barcode: str | None):
  qs = _wb_shipped_qs(seller)
  qs = _apply_date_filter(qs, field="in_delivery_at", date_from=date_from, date_to=date_to)
  if barcode:
    qs = qs.filter(barcode__icontains=barcode.strip())

  counts: dict[str, int] = defaultdict(int)
  for row in qs.values_list("barcode", flat=True):
    code = (row or "").strip()
    if code:
      counts[code] += 1
  return counts


def _aggregate_ozon(seller: Seller, *, date_from: date | None, date_to: date | None, barcode: str | None):
  qs = _ozon_shipped_qs(seller)
  qs = _apply_date_filter(qs, field="shipped_at", date_from=date_from, date_to=date_to)
  if barcode:
    qs = qs.filter(barcode__icontains=barcode.strip())

  counts: dict[str, int] = defaultdict(int)
  for barcode_value, quantity in qs.values_list("barcode", "quantity"):
    code = (barcode_value or "").strip()
    if not code:
      continue
    counts[code] += max(1, quantity or 1)
  return counts


def _product_meta(seller: Seller, *, marketplace: str) -> dict[str, dict]:
  mp = normalize_marketplace(marketplace)
  products = Product.objects.filter(seller=seller, marketplace=mp)
  return {
    product.barcode: {
      "name": product.name or "",
      "tech_size": (product.tech_size or product.wb_size or "").strip(),
      "vendor_code": (product.vendor_code or "").strip(),
    }
    for product in products
  }


def load_crm_product_shipment_stats(
  seller: Seller,
  *,
  marketplace: str = WB,
  period: str = PERIOD_ALL,
  date_from: date | None = None,
  date_to: date | None = None,
  barcode: str | None = None,
) -> dict:
  mp = normalize_marketplace(marketplace)
  range_from, range_to, preset = resolve_stats_period(
    period=period,
    date_from=date_from,
    date_to=date_to,
  )

  if mp == OZON:
    counts = _aggregate_ozon(seller, date_from=range_from, date_to=range_to, barcode=barcode)
  else:
    counts = _aggregate_wb(seller, date_from=range_from, date_to=range_to, barcode=barcode)

  meta = _product_meta(seller, marketplace=mp)
  items = []
  for code, units in counts.items():
    info = meta.get(code, {})
    items.append({
      "barcode": code,
      "name": info.get("name") or code,
      "tech_size": info.get("tech_size") or "",
      "vendor_code": info.get("vendor_code") or "",
      "units": units,
    })
  items.sort(key=lambda row: (-row["units"], row["barcode"]))

  crm_from, crm_to = _crm_bounds(seller, marketplace=mp)
  total_units = sum(row["units"] for row in items)

  return {
    "seller_id": seller.id,
    "company_name": seller.company_name,
    "marketplace": mp,
    "period": preset,
    "date_from": range_from.isoformat() if range_from else None,
    "date_to": range_to.isoformat() if range_to else None,
    "crm_data_from": crm_from.isoformat() if crm_from else None,
    "crm_data_to": crm_to.isoformat() if crm_to else None,
    "total_units": total_units,
    "items": items,
  }
