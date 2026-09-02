"""Удаление складов селлера из CRM (без повторного появления при синхронизации)."""
from __future__ import annotations

from django.db import transaction

from apps.integrations.marketplace import OZON, WB
from apps.integrations.models import AuditLog
from apps.sellers.models import (
  ExcludedSellerWarehouse,
  Seller,
  SellerOzonWarehouse,
  SellerWarehouse,
)


class WarehouseManageError(Exception):
  pass


def _excluded_external_ids(seller: Seller, marketplace: str) -> set[int]:
  return set(
    ExcludedSellerWarehouse.objects.filter(
      seller=seller,
      marketplace=marketplace,
    ).values_list("warehouse_external_id", flat=True)
  )


def excluded_wb_warehouse_ids(seller: Seller) -> set[int]:
  return _excluded_external_ids(seller, WB)


def excluded_ozon_warehouse_ids(seller: Seller) -> set[int]:
  return _excluded_external_ids(seller, OZON)


@transaction.atomic
def delete_seller_wb_warehouse(seller: Seller, warehouse_id: int, *, user=None) -> dict:
  warehouse = SellerWarehouse.objects.filter(pk=warehouse_id, seller=seller).first()
  if not warehouse:
    raise WarehouseManageError("Склад не найден")

  label = warehouse.name or f"Склад #{warehouse.wb_warehouse_id}"
  ExcludedSellerWarehouse.objects.get_or_create(
    seller=seller,
    marketplace=WB,
    warehouse_external_id=warehouse.wb_warehouse_id,
  )
  external_id = warehouse.wb_warehouse_id
  warehouse.delete()

  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.OTHER,
    message=f"Склад WB удалён из CRM: {label}",
    details={"wb_warehouse_id": external_id},
  )
  return {
    "detail": f"Склад «{label}» удалён и больше не появится при синхронизации",
    "wb_warehouse_id": external_id,
  }


@transaction.atomic
def delete_seller_ozon_warehouse(seller: Seller, warehouse_id: int, *, user=None) -> dict:
  warehouse = SellerOzonWarehouse.objects.filter(pk=warehouse_id, seller=seller).first()
  if not warehouse:
    raise WarehouseManageError("Склад не найден")

  label = warehouse.name or f"Склад #{warehouse.ozon_warehouse_id}"
  ExcludedSellerWarehouse.objects.get_or_create(
    seller=seller,
    marketplace=OZON,
    warehouse_external_id=warehouse.ozon_warehouse_id,
  )
  external_id = warehouse.ozon_warehouse_id
  warehouse.delete()

  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.OTHER,
    message=f"Склад Ozon удалён из CRM: {label}",
    details={"ozon_warehouse_id": external_id},
  )
  return {
    "detail": f"Склад «{label}» удалён и больше не появится при синхронизации",
    "ozon_warehouse_id": external_id,
  }
