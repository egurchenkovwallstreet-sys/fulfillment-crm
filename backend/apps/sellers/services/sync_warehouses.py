"""Синхронизация складов продавца из WB API."""
from __future__ import annotations

from django.utils import timezone

from apps.integrations.models import AuditLog
from apps.integrations.wb_client import WBApiError, WBClient
from apps.integrations.wb_crypto import TokenCryptoError, decrypt_token
from apps.sellers.models import Seller, SellerWarehouse
from apps.sellers.services.warehouse_manage import excluded_wb_warehouse_ids


class WarehouseSyncError(Exception):
  pass


def _get_client(seller: Seller) -> WBClient:
  if not seller.wb_api_token_encrypted:
    raise WarehouseSyncError(f"У селлера «{seller.company_name}» не задан токен WB")
  try:
    token = decrypt_token(seller.wb_api_token_encrypted)
  except TokenCryptoError as exc:
    raise WarehouseSyncError(str(exc)) from exc
  return WBClient(token)


def sync_seller_warehouses(seller: Seller, *, user=None) -> dict:
  client = _get_client(seller)
  try:
    remote = client.fetch_seller_warehouses()
  except WBApiError as exc:
    AuditLog.objects.create(
      user=user,
      seller=seller,
      action_type=AuditLog.ActionType.API_ERROR,
      message=f"Ошибка загрузки складов WB: {exc}",
      details={"status_code": exc.status_code},
    )
    raise WarehouseSyncError(str(exc)) from exc

  now = timezone.now()
  created = 0
  updated = 0
  skipped = 0
  excluded = excluded_wb_warehouse_ids(seller)
  for item in remote:
    wh_id = item.get("id")
    if wh_id is None:
      continue
    wh_id = int(wh_id)
    if wh_id in excluded:
      skipped += 1
      continue
    _, was_created = SellerWarehouse.objects.update_or_create(
      seller=seller,
      wb_warehouse_id=wh_id,
      defaults={
        "name": str(item.get("name") or "").strip(),
        "address": str(item.get("address") or "").strip(),
        "office_id": item.get("officeId"),
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
    action_type=AuditLog.ActionType.WB_SYNC,
    message=f"Синхронизация складов WB: {len(remote)} шт.",
    details={"created": created, "updated": updated, "skipped_excluded": skipped, "total": len(remote)},
  )

  return {
    "created": created,
    "updated": updated,
    "skipped_excluded": skipped,
    "total": len(remote),
  }
