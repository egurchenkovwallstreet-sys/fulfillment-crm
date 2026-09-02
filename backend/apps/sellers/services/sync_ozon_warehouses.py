"""Синхронизация складов продавца из Ozon Seller API."""
from __future__ import annotations

from django.utils import timezone

from apps.integrations.models import AuditLog
from apps.integrations.ozon_client import OzonApiError
from apps.orders.services.ozon_counts import OzonCountsError, ozon_client_for_seller
from apps.sellers.models import Seller, SellerOzonWarehouse
from apps.sellers.services.warehouse_manage import excluded_ozon_warehouse_ids


class OzonWarehouseSyncError(Exception):
  pass


def sync_seller_ozon_warehouses(seller: Seller, *, user=None) -> dict:
  try:
    client = ozon_client_for_seller(seller)
    remote = client.warehouse_list()
  except (OzonCountsError, OzonApiError) as exc:
    AuditLog.objects.create(
      user=user,
      seller=seller,
      action_type=AuditLog.ActionType.API_ERROR,
      message=f"Ошибка загрузки складов Ozon: {exc}",
    )
    raise OzonWarehouseSyncError(str(exc)) from exc

  now = timezone.now()
  created = 0
  updated = 0
  skipped = 0
  excluded = excluded_ozon_warehouse_ids(seller)
  for item in remote:
    if not isinstance(item, dict):
      continue
    wh_id = item.get("warehouse_id") or item.get("id")
    if wh_id is None:
      continue
    wh_id = int(wh_id)
    if wh_id in excluded:
      skipped += 1
      continue
    status = str(item.get("status") or "").lower()
    if status in {"disabled", "blocked"}:
      continue
    _, was_created = SellerOzonWarehouse.objects.update_or_create(
      seller=seller,
      ozon_warehouse_id=int(wh_id),
      defaults={
        "name": str(item.get("name") or "").strip(),
        "is_rfbs": bool(item.get("is_rfbs")),
        "synced_at": now,
      },
    )
    if was_created:
      created += 1
    else:
      updated += 1

  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.OTHER,
    message=f"Синхронизация складов Ozon: {len(remote)} шт.",
    details={"created": created, "updated": updated, "skipped_excluded": skipped, "total": len(remote)},
  )
  return {"created": created, "updated": updated, "skipped_excluded": skipped, "total": len(remote)}
