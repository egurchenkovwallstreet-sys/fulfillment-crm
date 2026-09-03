"""Фильтрация заказов по складам WB селлера."""
from __future__ import annotations

from django.db.models import QuerySet

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
  """ID складов и офисов WB для сопоставления с заказом (экран сборки FBS)."""
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
  """Склад включён для обслуживания фулфилментом (импорт заказов, сборка, дашборд)."""
  if not seller_has_warehouse_config(seller):
    return True
  if wb_warehouse_id is None:
    return False
  return wb_warehouse_id in get_enabled_wb_warehouse_ids(seller)


def filter_orders_for_seller(qs: QuerySet, seller: Seller) -> QuerySet:
  """Все заказы селлера — без фильтра по галочке склада в сборке."""
  return qs.filter(seller=seller)


def filter_orders_for_assembly(qs: QuerySet, seller: Seller) -> QuerySet:
  """Только заказы включённых складов — экран «Сборка FBS»."""
  if not seller_has_warehouse_config(seller):
    return qs.filter(seller=seller)
  enabled = get_enabled_wb_warehouse_ids(seller)
  if not enabled:
    return qs.none()
  return qs.filter(seller=seller, wb_warehouse_id__in=enabled)


def filter_orders_for_seller_cabinet(qs: QuerySet, seller: Seller) -> QuerySet:
  """Кабинет селлера: все FBS-склады селлера."""
  return qs.filter(seller=seller)


def filter_orders_queryset(qs: QuerySet, *, seller: Seller | None = None) -> QuerySet:
  if seller is not None:
    return filter_orders_for_seller(qs, seller)
  return qs
