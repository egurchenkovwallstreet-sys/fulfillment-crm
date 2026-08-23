"""Назначение тарифов обработки товарам селлера."""
from __future__ import annotations

from decimal import Decimal

from django.db import transaction

from apps.sellers.models import Seller
from apps.warehouse.models import PriceGroup, Product


class SellerPricingError(Exception):
  pass


def get_price_groups() -> list[PriceGroup]:
  return list(PriceGroup.objects.order_by("sort_order", "name"))


def get_seller_pricing_summary(seller: Seller) -> dict:
  products = Product.objects.filter(seller=seller)
  total_count = products.count()

  groups_payload: list[dict] = []
  for group in get_price_groups():
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

  group = PriceGroup.objects.filter(pk=price_group_id).first()
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
