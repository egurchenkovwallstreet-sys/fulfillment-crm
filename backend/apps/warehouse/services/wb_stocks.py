"""Синхронизация остатков CRM ↔ ЛК WB (FBS, по складу)."""
from __future__ import annotations

from apps.integrations.wb_client import WBApiError, WBClient
from apps.integrations.wb_crypto import TokenCryptoError, decrypt_token
from apps.sellers.models import Seller, SellerWarehouse


class WBStockError(Exception):
  pass

STOCK_MODE_INTAKE = "intake"
STOCK_MODE_SYNC_FROM_WB = "sync_from_wb"


def _get_wb_client(seller: Seller) -> WBClient:
  if not seller.wb_api_token_encrypted:
    raise WBStockError(f"У селлера «{seller.company_name}» не задан токен WB")
  try:
    token = decrypt_token(seller.wb_api_token_encrypted)
  except TokenCryptoError as exc:
    raise WBStockError(str(exc)) from exc
  return WBClient(token)


def get_seller_warehouse(seller: Seller, warehouse_pk: int) -> SellerWarehouse:
  warehouse = SellerWarehouse.objects.filter(pk=warehouse_pk, seller=seller).first()
  if not warehouse:
    raise WBStockError("Склад WB не найден. Загрузите склады из WB.")
  return warehouse


def fetch_wb_stock_for_barcode(
  seller: Seller,
  warehouse: SellerWarehouse,
  barcode: str,
) -> int:
  """Текущий остаток баркода на складе FBS в ЛК WB."""
  barcode = barcode.strip()
  if not barcode:
    raise WBStockError("Пустой баркод")

  client = _get_wb_client(seller)
  try:
    items = client.fetch_warehouse_stocks_by_skus(warehouse.wb_warehouse_id, [barcode])
  except WBApiError as exc:
    raise WBStockError(f"Не удалось получить остаток из WB: {exc}") from exc

  for item in items:
    sku = str(item.get("sku") or "").strip()
    if sku == barcode:
      try:
        return max(0, int(item.get("amount") or 0))
      except (TypeError, ValueError):
        return 0
  return 0


def push_wb_stock_increment(
  seller: Seller,
  warehouse: SellerWarehouse,
  barcode: str,
  add_quantity: int,
) -> dict:
  """Режим приёмки: текущий остаток WB + принятое количество."""
  if add_quantity <= 0:
    raise WBStockError("Количество должно быть больше 0")

  barcode = barcode.strip()
  current = fetch_wb_stock_for_barcode(seller, warehouse, barcode)
  new_amount = current + add_quantity

  client = _get_wb_client(seller)
  try:
    client.update_warehouse_stocks(
      warehouse.wb_warehouse_id,
      [{"sku": barcode, "amount": new_amount}],
    )
  except WBApiError as exc:
    raise WBStockError(f"Не удалось обновить остаток в WB: {exc}") from exc

  return {
    "wb_warehouse_id": warehouse.wb_warehouse_id,
    "warehouse_name": warehouse.name,
    "previous_wb_amount": current,
    "new_wb_amount": new_amount,
    "added": add_quantity,
  }
