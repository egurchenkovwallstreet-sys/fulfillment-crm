"""Расчёт литража и тарифов системы 2."""
from __future__ import annotations

import calendar
import math
from decimal import Decimal, ROUND_CEILING
from typing import TYPE_CHECKING

if TYPE_CHECKING:
  from apps.sellers.models import Seller
  from apps.warehouse.models import Product

ZERO = Decimal("0")
ONE = Decimal("1")
TENTH = Decimal("0.1")
HALF = Decimal("0.5")


def seller_uses_liter_pricing(seller: Seller) -> bool:
  return getattr(seller, "pricing_mode", "per_unit") == "per_liter"


def ceil_liters(raw: Decimal) -> Decimal:
  if raw <= ZERO:
    return ZERO
  return (raw / TENTH).quantize(Decimal("1"), rounding=ROUND_CEILING) * TENTH


def volume_from_cm(
  length_cm: Decimal | float | int | None,
  width_cm: Decimal | float | int | None,
  height_cm: Decimal | float | int | None,
) -> Decimal:
  if length_cm is None or width_cm is None or height_cm is None:
    return ZERO
  length = Decimal(str(length_cm))
  width = Decimal(str(width_cm))
  height = Decimal(str(height_cm))
  if length <= ZERO or width <= ZERO or height <= ZERO:
    return ZERO
  raw = length * width * height / Decimal("1000")
  return ceil_liters(raw)


def billable_extra_liters(extra: Decimal) -> Decimal:
  if extra <= ZERO:
    return ZERO
  if extra <= HALF:
    return HALF
  return Decimal(math.ceil(float(extra)))


def shipment_liter_cost(
  volume_liters: Decimal,
  *,
  has_marking: bool,
  seller: Seller,
) -> Decimal:
  if volume_liters <= ZERO:
    return ZERO

  cost = seller.first_liter_shipment_price
  extra = volume_liters - ONE
  extra_billed = billable_extra_liters(extra)
  if extra_billed > ZERO:
    cost += extra_billed * seller.next_liter_shipment_price
  if has_marking:
    cost += seller.marking_surcharge_per_unit
  return cost.quantize(Decimal("0.01"))


def daily_storage_cost(
  quantity: int,
  volume_liters: Decimal,
  *,
  seller: Seller,
  charge_date=None,
) -> Decimal:
  if quantity <= 0 or volume_liters <= ZERO:
    return ZERO
  if charge_date is not None:
    days_in_month = calendar.monthrange(charge_date.year, charge_date.month)[1]
  else:
    days_in_month = 30
  monthly = seller.storage_tariff_per_liter_month
  amount = Decimal(quantity) * volume_liters * monthly / Decimal(days_in_month)
  return amount.quantize(Decimal("0.01"))


def apply_product_dimensions(
  product: Product,
  *,
  length_cm: Decimal | float | int | None = None,
  width_cm: Decimal | float | int | None = None,
  height_cm: Decimal | float | int | None = None,
) -> Decimal:
  length = length_cm if length_cm is not None else product.length_cm
  width = width_cm if width_cm is not None else product.width_cm
  height = height_cm if height_cm is not None else product.height_cm
  volume = volume_from_cm(length, width, height)
  update_fields = []
  if length_cm is not None:
    product.length_cm = Decimal(str(length_cm))
    update_fields.extend(["length_cm"])
  if width_cm is not None:
    product.width_cm = Decimal(str(width_cm))
    update_fields.extend(["width_cm"])
  if height_cm is not None:
    product.height_cm = Decimal(str(height_cm))
    update_fields.extend(["height_cm"])
  if volume > ZERO:
    product.volume_liters = volume
    update_fields.append("volume_liters")
  if update_fields:
    product.save(update_fields=[*update_fields, "updated_at"])
  return volume


def product_volume_liters(product: Product) -> Decimal:
  if product.volume_liters and product.volume_liters > ZERO:
    return product.volume_liters
  volume = volume_from_cm(product.length_cm, product.width_cm, product.height_cm)
  if volume > ZERO and product.volume_liters != volume:
    product.volume_liters = volume
    product.save(update_fields=["volume_liters", "updated_at"])
  return volume
