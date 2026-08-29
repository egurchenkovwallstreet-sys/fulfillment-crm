"""Управление селлерами: токены API и удаление."""
from __future__ import annotations

from django.db import transaction
from django.db.models.deletion import ProtectedError

from apps.integrations.wb_crypto import encrypt_token
from apps.orders.services.ozon_counts import OzonCountsError, ping_seller_ozon, refresh_ozon_counts
from apps.sellers.models import Seller
from apps.sellers.services.sync_warehouses import WarehouseSyncError, sync_seller_warehouses


class SellerManageError(Exception):
  pass


def apply_wb_token(seller: Seller, token: str, *, user=None) -> tuple[bool, str]:
  token = (token or "").strip()
  if not token:
    raise SellerManageError("Вставьте персональный токен WB")

  seller.wb_api_token_encrypted = encrypt_token(token)
  seller.wb_enabled = True
  seller.save(update_fields=["wb_api_token_encrypted", "wb_enabled", "updated_at"])

  try:
    sync_seller_warehouses(seller, user=user)
    return True, "Токен WB сохранён. API отвечает, склады синхронизированы."
  except WarehouseSyncError as exc:
    return False, f"Токен сохранён, но проверка API не прошла: {exc}"


def clear_wb_token(seller: Seller) -> None:
  seller.wb_api_token_encrypted = ""
  seller.save(update_fields=["wb_api_token_encrypted", "updated_at"])


def apply_ozon_keys(seller: Seller, client_id: str, api_key: str) -> tuple[bool, str]:
  client_id = (client_id or "").strip()
  api_key = (api_key or "").strip()
  if not client_id or not api_key:
    raise SellerManageError("Укажите Client-Id и Api-Key из ЛК Ozon")

  seller.ozon_client_id = client_id
  seller.ozon_api_key_encrypted = encrypt_token(api_key)
  seller.ozon_enabled = True
  seller.save(
    update_fields=[
      "ozon_client_id",
      "ozon_api_key_encrypted",
      "ozon_enabled",
      "updated_at",
    ]
  )

  try:
    ping_seller_ozon(seller)
    refresh_ozon_counts(seller)
    return True, "Ключи сохранены. API Ozon отвечает."
  except OzonCountsError as exc:
    return False, f"Ключи сохранены, но проверка API не прошла: {exc}"


def clear_ozon_keys(seller: Seller) -> None:
  seller.ozon_client_id = ""
  seller.ozon_api_key_encrypted = ""
  seller.save(update_fields=["ozon_client_id", "ozon_api_key_encrypted", "updated_at"])


@transaction.atomic
def delete_seller(seller: Seller) -> None:
  name = seller.company_name
  try:
    seller.delete()
  except ProtectedError as exc:
    raise SellerManageError(
      "Нельзя удалить селлера: есть связанные заказы или складские операции. "
      "Сначала деактивируйте селлера или очистите историю."
    ) from exc
  except Exception as exc:
    raise SellerManageError(f"Не удалось удалить селлера «{name}»: {exc}") from exc
