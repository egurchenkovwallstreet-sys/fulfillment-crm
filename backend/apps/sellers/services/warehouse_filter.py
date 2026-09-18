"""Фильтрация заказов по складам WB селлера."""
from __future__ import annotations

from django.db.models import QuerySet

from apps.integrations.marketplace import WB
from apps.orders.models import Order, Supply
from apps.sellers.models import ExcludedSellerWarehouse, Seller, SellerWarehouse


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


def get_billing_warehouse_match_ids(seller: Seller) -> set[int]:
  """
  ID складов WB для биллинга и истории отгрузок.
  Включает включённые, отключённые, удалённые из CRM и склады из заказов/поставок.
  """
  match_ids: set[int] = set()
  for wh_id, office_id in SellerWarehouse.objects.filter(seller=seller).values_list(
    "wb_warehouse_id",
    "office_id",
  ):
    match_ids.add(int(wh_id))
    if office_id:
      match_ids.add(int(office_id))

  for ext_id in ExcludedSellerWarehouse.objects.filter(
    seller=seller,
    marketplace=WB,
  ).values_list("warehouse_external_id", flat=True):
    match_ids.add(int(ext_id))

  for wh_id in Order.objects.filter(
    seller=seller,
    wb_warehouse_id__isnull=False,
  ).values_list("wb_warehouse_id", flat=True).distinct():
    match_ids.add(int(wh_id))

  for wh_id in Supply.objects.filter(
    seller=seller,
    wb_warehouse_id__isnull=False,
  ).values_list("wb_warehouse_id", flat=True).distinct():
    match_ids.add(int(wh_id))

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


def resolve_enabled_seller_warehouse(
  seller: Seller,
  warehouse_id: int | None,
  office_id: int | None = None,
) -> SellerWarehouse | None:
  """
  Найти включённый склад селлера по warehouseId и/или officeId из заказа WB.
  WB в API часто отдаёт officeId вместо warehouseId — без этого заказы не импортировались.
  """
  if not seller_has_warehouse_config(seller):
    return None
  wh_id = int(warehouse_id) if warehouse_id is not None else None
  off_id = int(office_id) if office_id is not None else None
  if wh_id is None and off_id is None:
    return None
  for warehouse in SellerWarehouse.objects.filter(seller=seller, is_enabled=True):
    match_ids = {warehouse.wb_warehouse_id}
    if warehouse.office_id:
      match_ids.add(int(warehouse.office_id))
    if wh_id is not None and wh_id in match_ids:
      return warehouse
    if off_id is not None and off_id in match_ids:
      return warehouse
  return None


def resolve_wb_order_warehouse_id(
  seller: Seller,
  warehouse_id: int | None,
  office_id: int | None = None,
) -> int | None:
  """Канонический wb_warehouse_id для Order — из включённого склада селлера."""
  if not seller_has_warehouse_config(seller):
    if warehouse_id is not None:
      return int(warehouse_id)
    if office_id is not None:
      return int(office_id)
    return None
  resolved = resolve_enabled_seller_warehouse(seller, warehouse_id, office_id)
  return resolved.wb_warehouse_id if resolved else None


def is_warehouse_enabled(
  seller: Seller,
  wb_warehouse_id: int | None,
  office_id: int | None = None,
) -> bool:
  """Склад включён для обслуживания фулфилментом (импорт заказов, сборка, дашборд)."""
  if not seller_has_warehouse_config(seller):
    return True
  return resolve_enabled_seller_warehouse(seller, wb_warehouse_id, office_id) is not None


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


def filter_supplies_for_assembly(qs: QuerySet, seller: Seller) -> QuerySet:
  """Поставки только включённых FBS-складов — сборка и доставка в CRM."""
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
