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
  ExcludedSellerWarehouse.objects.update_or_create(
    seller=seller,
    marketplace=WB,
    warehouse_external_id=warehouse.wb_warehouse_id,
    defaults={"name": label},
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
  ExcludedSellerWarehouse.objects.update_or_create(
    seller=seller,
    marketplace=OZON,
    warehouse_external_id=warehouse.ozon_warehouse_id,
    defaults={"name": label},
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


def serialize_excluded_warehouse(row: ExcludedSellerWarehouse) -> dict:
  return {
    "id": row.id,
    "marketplace": row.marketplace,
    "warehouse_external_id": row.warehouse_external_id,
    "name": (row.name or "").strip() or f"Склад #{row.warehouse_external_id}",
    "excluded_at": row.excluded_at.isoformat() if row.excluded_at else None,
  }


def list_excluded_warehouses(seller: Seller) -> list[dict]:
  rows = ExcludedSellerWarehouse.objects.filter(seller=seller).order_by("marketplace", "name", "warehouse_external_id")
  return [serialize_excluded_warehouse(row) for row in rows]


def restore_excluded_warehouse(
  seller: Seller,
  *,
  marketplace: str,
  warehouse_external_id: int,
  user=None,
) -> dict:
  """Снять запрет и снова завести склад в CRM (включён для сборки и списания)."""
  from apps.integrations.marketplace import normalize_marketplace
  from apps.sellers.services.sync_ozon_warehouses import OzonWarehouseSyncError, sync_seller_ozon_warehouses
  from apps.sellers.services.sync_warehouses import WarehouseSyncError, sync_seller_warehouses

  raw_mp = str(marketplace or "").strip().lower()
  if raw_mp not in {WB, OZON, "озон"}:
    raise WarehouseManageError("Укажите маркетплейс: WB или Ozon")
  mp = normalize_marketplace(raw_mp)
  try:
    external_id = int(warehouse_external_id)
  except (TypeError, ValueError) as exc:
    raise WarehouseManageError("Укажите склад") from exc

  row = ExcludedSellerWarehouse.objects.filter(
    seller=seller,
    marketplace=mp,
    warehouse_external_id=external_id,
  ).first()
  if not row:
    raise WarehouseManageError("Этот склад не в списке удалённых")

  label = (row.name or "").strip() or f"Склад #{external_id}"
  row.delete()

  sync_error = ""
  restored = False
  if mp == WB:
    try:
      sync_seller_warehouses(seller, user=user)
    except WarehouseSyncError as exc:
      sync_error = str(exc)
    restored = SellerWarehouse.objects.filter(seller=seller, wb_warehouse_id=external_id).exists()
    if restored:
      SellerWarehouse.objects.filter(seller=seller, wb_warehouse_id=external_id).update(is_enabled=True)
  else:
    try:
      sync_seller_ozon_warehouses(seller, user=user)
    except OzonWarehouseSyncError as exc:
      sync_error = str(exc)
    restored = SellerOzonWarehouse.objects.filter(seller=seller, ozon_warehouse_id=external_id).exists()
    if restored:
      SellerOzonWarehouse.objects.filter(seller=seller, ozon_warehouse_id=external_id).update(is_enabled=True)

  if restored:
    detail = (
      f"Склад «{label}» снова в CRM и включён для сборки. "
      "При печати стикера остаток списывается как у обычного склада."
    )
  elif sync_error:
    detail = (
      f"Склад «{label}» снят с запрета, но подтянуть из ЛК не удалось: {sync_error}"
    )
  else:
    detail = (
      f"Склад «{label}» снят с запрета, но его сейчас нет в ЛК. "
      "Когда появится — вернётся при «Обновить из ЛК»."
    )

  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.OTHER,
    message=f"Склад возвращён в CRM: {label}",
    details={
      "marketplace": mp,
      "warehouse_external_id": external_id,
      "restored": restored,
    },
  )
  return {
    "detail": detail,
    "restored": restored,
    "marketplace": mp,
    "warehouse_external_id": external_id,
    "excluded": list_excluded_warehouses(seller),
  }
