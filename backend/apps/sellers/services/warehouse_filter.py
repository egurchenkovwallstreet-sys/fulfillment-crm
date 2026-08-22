"""Фильтрация заказов по включённым складам WB селлера."""
from __future__ import annotations

from django.db.models import Q, QuerySet

from apps.sellers.models import Seller, SellerWarehouse


def seller_has_warehouse_config(seller: Seller) -> bool:
  return SellerWarehouse.objects.filter(seller=seller).exists()


def get_enabled_wb_warehouse_ids(seller: Seller) -> set[int]:
  return set(
    SellerWarehouse.objects.filter(seller=seller, is_enabled=True).values_list(
      "wb_warehouse_id",
      flat=True,
    )
  )


def get_enabled_warehouse_match_ids(seller: Seller) -> set[int]:
  """ID складов и офисов WB для сопоставления с заказом."""
  match_ids: set[int] = set()
  for wh_id, office_id in SellerWarehouse.objects.filter(
    seller=seller,
    is_enabled=True,
  ).values_list("wb_warehouse_id", "office_id"):
    match_ids.add(wh_id)
    if office_id:
      match_ids.add(office_id)
  return match_ids


def order_matches_enabled_warehouse(
  seller: Seller,
  warehouse_id: int | None,
  office_id: int | None,
  *,
  match_ids: set[int] | None = None,
) -> bool:
  match_ids = match_ids if match_ids is not None else get_enabled_warehouse_match_ids(seller)
  if not match_ids:
    return False
  if warehouse_id is not None and warehouse_id in match_ids:
    return True
  if office_id is not None and office_id in match_ids:
    return True
  return False


def is_warehouse_enabled(seller: Seller, wb_warehouse_id: int | None) -> bool:
  if not seller_has_warehouse_config(seller):
    return True
  if wb_warehouse_id is None:
    return False
  return wb_warehouse_id in get_enabled_wb_warehouse_ids(seller)


def filter_orders_for_seller(qs: QuerySet, seller: Seller) -> QuerySet:
  """Только заказы включённых складов — как в live-счётчиках WB."""
  if not seller_has_warehouse_config(seller):
    return qs.filter(seller=seller)
  enabled = get_enabled_wb_warehouse_ids(seller)
  if not enabled:
    return qs.none()
  return qs.filter(seller=seller, wb_warehouse_id__in=enabled)


def filter_orders_for_seller_cabinet(qs: QuerySet, seller: Seller) -> QuerySet:
  """Кабинет селлера: только обслуживаемые FBS-склады, без fallback на все заказы."""
  enabled = get_enabled_wb_warehouse_ids(seller)
  if not enabled:
    return qs.none()
  return qs.filter(seller=seller, wb_warehouse_id__in=enabled)


def filter_orders_queryset(qs: QuerySet, *, seller: Seller | None = None) -> QuerySet:
  if seller is not None:
    return filter_orders_for_seller(qs, seller)
  if not SellerWarehouse.objects.exists():
    return qs
  enabled_pairs = list(
    SellerWarehouse.objects.filter(is_enabled=True).values_list(
      "seller_id",
      "wb_warehouse_id",
    )
  )
  if not enabled_pairs:
    return qs.none()
  condition = Q()
  sellers_with_config = set(
    SellerWarehouse.objects.values_list("seller_id", flat=True).distinct()
  )
  for seller_id, wh_id in enabled_pairs:
    condition |= Q(seller_id=seller_id, wb_warehouse_id=wh_id)
  sellers_without_config = Seller.objects.exclude(id__in=sellers_with_config).values_list(
    "id",
    flat=True,
  )
  if sellers_without_config:
    condition |= Q(seller_id__in=sellers_without_config)
  return qs.filter(condition)
