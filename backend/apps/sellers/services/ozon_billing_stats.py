"""Отгрузки Ozon FBS — по факту ship в CRM (передача к отгрузке)."""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.utils import timezone

from apps.integrations.marketplace import OZON
from apps.orders.models import OzonPosting
from apps.sellers.models import Seller
from apps.sellers.services.calendar_periods import (
  calendar_week_bounds,
  calendar_week_bounds_offset,
  today_local,
)
from apps.sellers.services.seller_billing_stats import (
  SHIPMENTS_WEEKS_HISTORY,
  _barcode_price_map,
  _build_week_payload,
  _seller_fallback_tariff,
  _week_start_for,
)


def load_weekly_ozon_shipped_orders(seller: Seller, *, weeks: int = SHIPMENTS_WEEKS_HISTORY) -> dict:
  """
  Отправления Ozon, переданные к отгрузке через CRM (ship), по календарным неделям.
  Сумма — тариф обработки × количество единиц в отправлении.
  """
  today = today_local()
  current_week_start, current_week_end = calendar_week_bounds(today)
  oldest_week_start, _ = calendar_week_bounds_offset(weeks - 1, today)

  daily_counts: dict[date, int] = defaultdict(int)
  daily_amounts: dict[date, Decimal] = defaultdict(lambda: Decimal("0"))
  carriages_per_week: dict[date, set[int]] = defaultdict(set)

  price_by_barcode = _barcode_price_map(seller, marketplace=OZON)
  fallback_tariff = _seller_fallback_tariff(seller, marketplace=OZON)

  qs = OzonPosting.objects.filter(
    seller=seller,
    shipped_at__isnull=False,
    shipped_at__date__gte=oldest_week_start,
    shipped_at__date__lte=current_week_end,
  )

  for posting in qs.iterator():
    ship_date = timezone.localtime(posting.shipped_at).date()
    qty = max(1, posting.quantity or 1)
    unit_price = price_by_barcode.get((posting.barcode or "").strip()) or fallback_tariff
    daily_counts[ship_date] += qty
    if unit_price is not None:
      daily_amounts[ship_date] += unit_price * qty
    if posting.carriage_id:
      carriages_per_week[_week_start_for(ship_date)].add(int(posting.carriage_id))

  supplies_per_week = {
    week_start: len(carriage_ids)
    for week_start, carriage_ids in carriages_per_week.items()
  }

  weeks_data = [
    _build_week_payload(
      *calendar_week_bounds_offset(weeks_ago, today),
      daily_counts=daily_counts,
      daily_amounts=daily_amounts,
      supplies_per_week=supplies_per_week,
      today=today,
    )
    for weeks_ago in range(weeks)
  ]
  return {
    "today": today.isoformat(),
    "weeks": weeks_data,
  }
