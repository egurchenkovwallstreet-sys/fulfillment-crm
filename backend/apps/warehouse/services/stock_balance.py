"""Единая логика CRM vs ЛК WB с учётом заказов «Новые»."""
from __future__ import annotations

from apps.integrations.marketplace import OZON, WB, normalize_marketplace
from apps.orders.services.supply_flow import (
  count_new_orders_for_barcode,
  count_new_orders_for_barcode_on_warehouse,
  count_picking_orders_for_barcode,
)
from apps.sellers.models import Seller, SellerWarehouse


def count_reserved_new_orders(
  seller: Seller,
  barcode: str,
  *,
  marketplace: str = WB,
) -> int:
  mp = normalize_marketplace(marketplace)
  if mp == OZON:
    return 0
  return count_new_orders_for_barcode(seller, barcode.strip())


def count_reserved_new_orders_on_warehouse(
  seller: Seller,
  barcode: str,
  warehouse: SellerWarehouse,
  *,
  marketplace: str = WB,
) -> int:
  mp = normalize_marketplace(marketplace)
  if mp == OZON:
    return 0
  return count_new_orders_for_barcode_on_warehouse(
    seller,
    barcode.strip(),
    warehouse.wb_warehouse_id,
  )


def compute_wb_amount_from_crm(crm_quantity: int, reserved_new: int) -> tuple[int, bool]:
  """Возвращает (остаток для ЛК WB, нужна_догрузка)."""
  crm_quantity = max(0, int(crm_quantity))
  reserved_new = max(0, int(reserved_new))
  if reserved_new > crm_quantity:
    return 0, True
  return crm_quantity - reserved_new, False


def count_reserved_open_orders(
  seller: Seller,
  barcode: str,
  *,
  marketplace: str = WB,
) -> int:
  """Заказы «Новые» + «На сборке» по баркоду на рабочих FBS-складах."""
  mp = normalize_marketplace(marketplace)
  if mp == OZON:
    return 0
  code = barcode.strip()
  if not code:
    return 0
  return count_new_orders_for_barcode(seller, code) + count_picking_orders_for_barcode(seller, code)
