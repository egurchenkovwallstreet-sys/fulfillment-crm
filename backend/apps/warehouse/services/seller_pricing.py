"""Назначение тарифов обработки товарам селлера."""
from __future__ import annotations

from decimal import Decimal

from django.db import transaction

from apps.sellers.models import Seller
from apps.warehouse.models import PriceGroup, Product


class SellerPricingError(Exception):
  pass


def get_price_groups(*, fulfillment) -> list[PriceGroup]:
  return list(PriceGroup.objects.filter(fulfillment=fulfillment).order_by("sort_order", "name"))


def get_seller_pricing_summary(seller: Seller) -> dict:
  products = Product.objects.filter(seller=seller)
  total_count = products.count()

  groups_payload: list[dict] = []
  for group in get_price_groups(fulfillment=seller.fulfillment):
    group_products = products.filter(price_group=group)
    count = group_products.count()
    if count == 0:
      continue
    individual_prices = list(group_products.values_list("individual_price", flat=True))
    non_null = [price for price in individual_prices if price is not None]
    if non_null and len(set(non_null)) == 1 and len(non_null) == count:
      tariff = non_null[0]
      mixed_tariffs = False
    elif non_null and len(set(non_null)) > 1:
      tariff = None
      mixed_tariffs = True
    else:
      tariff = None
      mixed_tariffs = False
    groups_payload.append({
      "id": group.id,
      "name": group.name,
      "default_price": group.processing_price,
      "product_count": count,
      "tariff": tariff,
      "mixed_tariffs": mixed_tariffs,
    })

  ungrouped_count = products.filter(price_group__isnull=True).count()
  all_individual = list(products.values_list("individual_price", flat=True))
  if total_count and all(price is not None for price in all_individual):
    unique_prices = set(all_individual)
    common_tariff = all_individual[0] if len(unique_prices) == 1 else None
    mixed_all = len(unique_prices) > 1
  else:
    common_tariff = None
    mixed_all = any(price is not None for price in all_individual)

  return {
    "seller_id": seller.id,
    "company_name": seller.company_name,
    "product_count": total_count,
    "ungrouped_count": ungrouped_count,
    "common_tariff": common_tariff,
    "mixed_common_tariff": mixed_all and common_tariff is None,
    "groups": groups_payload,
  }


@transaction.atomic
def apply_seller_tariff(
  seller: Seller,
  *,
  scope: str,
  price: Decimal,
  price_group_id: int | None = None,
  assign_group: bool = False,
) -> dict:
  if price < 0:
    raise SellerPricingError("Тариф не может быть отрицательным")

  products = Product.objects.filter(seller=seller).select_for_update()

  if scope == "all":
    updated = products.update(individual_price=price)
    return {"updated": updated, "scope": scope}

  if scope != "group":
    raise SellerPricingError("Неизвестный тип тарифа")

  if price_group_id is None:
    raise SellerPricingError("Укажите ценовую группу")

  group = PriceGroup.objects.filter(pk=price_group_id, fulfillment=seller.fulfillment).first()
  if group is None:
    raise SellerPricingError("Ценовая группа не найдена")

  if assign_group:
    products.filter(price_group__isnull=True).update(price_group=group)

  qs = products.filter(price_group=group)
  updated = qs.update(individual_price=price)
  if updated == 0:
    raise SellerPricingError(
      f"У селлера нет товаров в группе «{group.name}». "
      "Включите «Назначить группу товарам без группы» или задайте общий тариф."
    )

  return {
    "updated": updated,
    "scope": scope,
    "price_group_id": group.id,
    "price_group_name": group.name,
  }


@transaction.atomic
def apply_seller_liter_tariff(
  seller: Seller,
  *,
  pricing_mode: str,
  first_liter_shipment_price: Decimal | None = None,
  next_liter_shipment_price: Decimal | None = None,
  marking_surcharge_per_unit: Decimal | None = None,
  storage_tariff_per_liter_month: Decimal | None = None,
) -> dict:
  if pricing_mode not in (Seller.PricingMode.PER_UNIT, Seller.PricingMode.PER_LITER):
    raise SellerPricingError("Неизвестный режим тарификации")

  seller.pricing_mode = pricing_mode
  update_fields = ["pricing_mode", "updated_at"]

  if first_liter_shipment_price is not None:
    if first_liter_shipment_price < 0:
      raise SellerPricingError("Тариф не может быть отрицательным")
    seller.first_liter_shipment_price = first_liter_shipment_price
    update_fields.append("first_liter_shipment_price")
  if next_liter_shipment_price is not None:
    if next_liter_shipment_price < 0:
      raise SellerPricingError("Тариф не может быть отрицательным")
    seller.next_liter_shipment_price = next_liter_shipment_price
    update_fields.append("next_liter_shipment_price")
  if marking_surcharge_per_unit is not None:
    if marking_surcharge_per_unit < 0:
      raise SellerPricingError("Тариф не может быть отрицательным")
    seller.marking_surcharge_per_unit = marking_surcharge_per_unit
    update_fields.append("marking_surcharge_per_unit")
  if storage_tariff_per_liter_month is not None:
    if storage_tariff_per_liter_month < 0:
      raise SellerPricingError("Тариф не может быть отрицательным")
    seller.storage_tariff_per_liter_month = storage_tariff_per_liter_month
    update_fields.append("storage_tariff_per_liter_month")

  seller.save(update_fields=update_fields)
  return {"pricing_mode": seller.pricing_mode}
