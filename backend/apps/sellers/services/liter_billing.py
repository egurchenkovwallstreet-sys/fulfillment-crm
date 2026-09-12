"""Начисления и отчёты по литражу (система 2)."""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.integrations.marketplace import OZON, WB, normalize_marketplace
from apps.orders.models import Order, OzonPosting
from apps.sellers.models import DailyStorageCharge, Seller, ShipmentLiterCharge
from apps.sellers.services.calendar_periods import calendar_week_bounds_offset, iter_week_days, today_local
from apps.warehouse.models import Product, ProductDailyQuantity
from apps.warehouse.services.liter_pricing import (
  daily_storage_cost,
  product_volume_liters,
  seller_uses_liter_pricing,
  shipment_liter_cost,
)
from apps.warehouse.services.storage_stock_tracking import (
  first_positive_quantity_date,
  iter_positive_quantity_days,
  record_product_daily_quantity,
)

logger = logging.getLogger(__name__)
ZERO = Decimal("0")


def record_shipment_liter_charge_for_order(order: Order, *, seller: Seller) -> ShipmentLiterCharge | None:
  if not seller_uses_liter_pricing(seller):
    return None
  if ShipmentLiterCharge.objects.filter(order=order).exists():
    return ShipmentLiterCharge.objects.filter(order=order).first()

  product = order.product
  if not product:
    return None
  volume = product_volume_liters(product)
  if volume <= ZERO:
    logger.warning("liter shipment skipped: no volume for order %s barcode %s", order.id, order.barcode)
    return None

  has_marking = bool(product.requires_marking and (order.marking_bound or order.marking_code))
  amount = shipment_liter_cost(volume, has_marking=has_marking, seller=seller)
  charge_date = (order.in_delivery_at or timezone.now()).date()

  return ShipmentLiterCharge.objects.create(
    seller=seller,
    product=product,
    barcode=order.barcode or product.barcode,
    marketplace=WB,
    order=order,
    charge_date=charge_date,
    volume_liters=volume,
    has_marking=has_marking,
    amount=amount,
  )


def record_shipment_liter_charge_for_ozon_posting(posting: OzonPosting, *, seller: Seller) -> ShipmentLiterCharge | None:
  if not seller_uses_liter_pricing(seller):
    return None
  if ShipmentLiterCharge.objects.filter(ozon_posting=posting).exists():
    return ShipmentLiterCharge.objects.filter(ozon_posting=posting).first()

  product = Product.objects.filter(
    seller=seller,
    marketplace=OZON,
    barcode=posting.barcode,
  ).first()
  if not product:
    return None
  volume = product_volume_liters(product)
  if volume <= ZERO:
    return None

  has_marking = bool(product.requires_marking and posting.marking_bound)
  amount = shipment_liter_cost(volume, has_marking=has_marking, seller=seller) * Decimal(posting.quantity or 1)
  charge_date = (posting.shipped_at or timezone.now()).date()

  return ShipmentLiterCharge.objects.create(
    seller=seller,
    product=product,
    barcode=posting.barcode,
    marketplace=OZON,
    ozon_posting=posting,
    charge_date=charge_date,
    volume_liters=volume,
    has_marking=has_marking,
    amount=amount,
  )


def _upsert_daily_storage_charge(
  *,
  seller: Seller,
  product: Product,
  charge_date,
  quantity: int,
  volume,
) -> bool:
  amount = daily_storage_cost(quantity, volume, seller=seller, charge_date=charge_date)
  _, was_created = DailyStorageCharge.objects.update_or_create(
    seller=seller,
    product=product,
    charge_date=charge_date,
    defaults={
      "quantity": quantity,
      "volume_liters": volume,
      "amount": amount,
    },
  )
  return was_created


def sync_storage_charges_for_product(
  product: Product,
  *,
  seller: Seller | None = None,
  from_date=None,
  to_date=None,
  force_recalc: bool = False,
) -> int:
  """Начислить хранение за все дни с положительным CRM-остатком."""
  seller = seller or product.seller
  volume = product_volume_liters(product)
  if volume <= ZERO:
    return 0

  to_date = to_date or today_local()
  if from_date is None:
    from_date = first_positive_quantity_date(product)
  if from_date is None or from_date > to_date:
    return 0

  existing_dates: set = set()
  if not force_recalc:
    existing_dates = set(
      DailyStorageCharge.objects.filter(
        seller=seller,
        product=product,
        charge_date__gte=from_date,
        charge_date__lte=to_date,
      ).values_list("charge_date", flat=True)
    )

  positive_days = iter_positive_quantity_days(product, from_date, to_date)
  positive_dates = {charge_date for charge_date, _ in positive_days}

  touched = 0
  for charge_date, quantity in positive_days:
    if not force_recalc and charge_date in existing_dates:
      continue
    _upsert_daily_storage_charge(
      seller=seller,
      product=product,
      charge_date=charge_date,
      quantity=quantity,
      volume=volume,
    )
    touched += 1

  deleted, _ = DailyStorageCharge.objects.filter(
    seller=seller,
    product=product,
    charge_date__gte=from_date,
    charge_date__lte=to_date,
  ).exclude(charge_date__in=positive_dates).delete()
  return touched + deleted


@transaction.atomic
def accrue_daily_storage_for_seller(seller: Seller, charge_date=None) -> int:
  if charge_date is None:
    charge_date = today_local()

  touched = 0
  product_ids = set(
    Product.objects.filter(seller=seller, quantity__gt=0).values_list("id", flat=True)
  )
  product_ids.update(
    ProductDailyQuantity.objects.filter(
      product__seller=seller,
      quantity__gt=0,
      date__lte=charge_date,
    ).values_list("product_id", flat=True)
  )

  for product in Product.objects.filter(seller=seller, id__in=product_ids):
    record_product_daily_quantity(product, on_date=charge_date)
    touched += sync_storage_charges_for_product(
      product,
      seller=seller,
      to_date=charge_date,
    )
  return touched


def accrue_daily_storage_all_sellers() -> dict:
  charge_date = today_local()
  total = 0
  sellers = 0
  for seller in Seller.objects.filter(is_active=True):
    try:
      count = accrue_daily_storage_for_seller(seller, charge_date)
      total += count
      sellers += 1
    except Exception:
      logger.exception("daily storage accrual failed for seller %s", seller.id)
  return {"date": charge_date.isoformat(), "sellers": sellers, "products": total}


def _empty_week_chart(weeks: int = 4) -> dict:
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
  return {"today": today.isoformat(), "weeks": weeks_data}


def _aggregate_charges_by_week(
  charges: list[tuple],
  *,
  count_field: str = "orders",
) -> dict:
  today = today_local()
  weeks_data = []
  for weeks_ago in range(4):
    week_start, week_end = calendar_week_bounds_offset(weeks_ago, today)
    day_amounts: dict[str, Decimal] = defaultdict(lambda: ZERO)
    day_counts: dict[str, int] = defaultdict(int)
    total_amount = ZERO
    total_count = 0
    for charge_date, amount, count in charges:
      if charge_date < week_start or charge_date > week_end:
        continue
      key = charge_date.isoformat()
      day_amounts[key] += amount
      day_counts[key] += count
      total_amount += amount
      total_count += count
    weeks_data.append({
      "week_start": week_start.isoformat(),
      "week_end": week_end.isoformat(),
      "total": total_count,
      "total_amount": f"{total_amount:.2f}",
      "supplies_count": 0,
      "is_current": weeks_ago == 0,
      "days": [
        {
          "date": day.isoformat(),
          "weekday": label,
          "orders": day_counts.get(day.isoformat(), 0),
          "amount": f"{day_amounts.get(day.isoformat(), ZERO):.2f}",
        }
        for day, label in iter_week_days(week_start)
      ],
    })
  return {"today": today.isoformat(), "weeks": weeks_data}


def load_weekly_storage_charges(seller: Seller, *, marketplace: str = WB) -> dict:
  mp = normalize_marketplace(marketplace)
  today = today_local()
  week_start, _ = calendar_week_bounds_offset(3, today)
  qs = DailyStorageCharge.objects.filter(
    seller=seller,
    charge_date__gte=week_start,
    product__marketplace=mp,
  ).values_list("charge_date", "amount")
  charges = [(d, a, 1) for d, a in qs]
  return _aggregate_charges_by_week(charges, count_field="skus")


def load_weekly_liter_shipment_charges(seller: Seller, *, marketplace: str = WB) -> dict:
  if not seller_uses_liter_pricing(seller):
    return _empty_week_chart()
  mp = normalize_marketplace(marketplace)
  today = today_local()
  week_start, _ = calendar_week_bounds_offset(3, today)
  qs = ShipmentLiterCharge.objects.filter(
    seller=seller,
    charge_date__gte=week_start,
    marketplace=mp,
  ).values_list("charge_date", "amount")
  charges = [(d, a, 1) for d, a in qs]
  return _aggregate_charges_by_week(charges, count_field="orders")


def load_storage_by_barcode(seller: Seller, *, marketplace: str = WB, days: int = 30) -> list[dict]:
  mp = normalize_marketplace(marketplace)
  since = today_local() - timedelta(days=days - 1)
  rows = (
    DailyStorageCharge.objects.filter(
      seller=seller,
      charge_date__gte=since,
      product__marketplace=mp,
    )
    .select_related("product")
    .order_by("product__barcode", "-charge_date")
  )
  totals: dict[str, dict] = {}
  for row in rows:
    barcode = row.product.barcode
    bucket = totals.setdefault(barcode, {
      "barcode": barcode,
      "name": row.product.name,
      "quantity": row.quantity,
      "volume_liters": str(row.volume_liters),
      "amount": ZERO,
    })
    bucket["amount"] += row.amount
    bucket["quantity"] = row.quantity
  return [
    {**item, "amount": f"{item['amount']:.2f}"}
    for item in sorted(totals.values(), key=lambda x: Decimal(x["amount"]), reverse=True)
  ]


def liter_tariff_payload(seller: Seller) -> dict:
  return {
    "pricing_mode": seller.pricing_mode,
    "first_liter_shipment_price": str(seller.first_liter_shipment_price),
    "next_liter_shipment_price": str(seller.next_liter_shipment_price),
    "marking_surcharge_per_unit": str(seller.marking_surcharge_per_unit),
    "storage_tariff_per_liter_month": str(seller.storage_tariff_per_liter_month),
  }
