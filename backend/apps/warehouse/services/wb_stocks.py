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


def get_enabled_seller_warehouses(seller: Seller) -> list[SellerWarehouse]:
  return list(
    SellerWarehouse.objects.filter(seller=seller).order_by("name", "id")
  )


def _parse_stock_amount(item: dict) -> int:
  try:
    return max(0, int(item.get("amount") or 0))
  except (TypeError, ValueError):
    return 0


def fetch_wb_stocks_for_warehouses(
  seller: Seller,
  warehouses: list[SellerWarehouse],
  barcodes: list[str],
) -> dict[str, dict]:
  """Остатки по баркодам на указанных FBS-складах (сумма total + by_warehouse)."""
  if not warehouses:
    raise WBStockError("Не выбраны FBS-склады")

  normalized = [b.strip() for b in barcodes if b and b.strip()]
  result: dict[str, dict] = {
    barcode: {"total": 0, "by_warehouse": {}} for barcode in normalized
  }
  if not normalized:
    return result

  client = _get_wb_client(seller)
  stock_by_sku: dict[str, dict[int, int]] = {barcode: {} for barcode in normalized}

  for warehouse in warehouses:
    try:
      items = client.fetch_warehouse_stocks_by_skus(warehouse.wb_warehouse_id, normalized)
    except WBApiError as exc:
      raise WBStockError(
        f"Ошибка остатков склада {warehouse.name or warehouse.wb_warehouse_id}: {exc}"
      ) from exc

    for item in items:
      sku = str(item.get("sku") or "").strip()
      if sku not in stock_by_sku:
        continue
      stock_by_sku[sku][warehouse.id] = _parse_stock_amount(item)

  for barcode in normalized:
    by_wh = stock_by_sku[barcode]
    result[barcode] = {"total": sum(by_wh.values()), "by_warehouse": by_wh}

  return result


def increment_product_warehouse_stock(
  product,
  warehouse: SellerWarehouse,
  add_quantity: int,
) -> int:
  """Увеличить остаток товара на конкретном FBS-складе в CRM."""
  from apps.warehouse.models import ProductWarehouseStock

  if add_quantity <= 0:
    return 0
  pws, _ = ProductWarehouseStock.objects.get_or_create(
    product=product,
    seller_warehouse=warehouse,
    defaults={"quantity": 0},
  )
  pws.quantity += add_quantity
  pws.save(update_fields=["quantity", "updated_at"])
  return pws.quantity


def fetch_summed_wb_stocks(
  seller: Seller,
  barcodes: list[str],
) -> dict[str, dict]:
  """
  Остатки по баркодам с суммированием по включённым FBS-складам.
  Возвращает {barcode: {total, by_warehouse: {seller_warehouse_pk: qty}}}.
  """
  warehouses = get_enabled_seller_warehouses(seller)
  if not warehouses:
    raise WBStockError("Нет включённых FBS-складов у селлера")

  normalized = [b.strip() for b in barcodes if b and b.strip()]
  result: dict[str, dict] = {
    barcode: {"total": 0, "by_warehouse": {}} for barcode in normalized
  }
  if not normalized:
    return result

  client = _get_wb_client(seller)
  stock_by_sku: dict[str, dict[int, int]] = {barcode: {} for barcode in normalized}

  for warehouse in warehouses:
    try:
      items = client.fetch_warehouse_stocks_by_skus(warehouse.wb_warehouse_id, normalized)
    except WBApiError as exc:
      raise WBStockError(
        f"Ошибка остатков склада {warehouse.name or warehouse.wb_warehouse_id}: {exc}"
      ) from exc

    for item in items:
      sku = str(item.get("sku") or "").strip()
      if sku not in stock_by_sku:
        continue
      stock_by_sku[sku][warehouse.id] = _parse_stock_amount(item)

  for barcode in normalized:
    by_wh = stock_by_sku[barcode]
    total = sum(by_wh.values())
    result[barcode] = {"total": total, "by_warehouse": by_wh}

  return result


def set_wb_stock_absolute(
  seller: Seller,
  warehouse: SellerWarehouse,
  barcode: str,
  amount: int,
) -> int:
  """Установить абсолютный остаток на складе WB."""
  barcode = barcode.strip()
  amount = max(0, int(amount))
  client = _get_wb_client(seller)
  try:
    client.update_warehouse_stocks(
      warehouse.wb_warehouse_id,
      [{"sku": barcode, "amount": amount}],
    )
  except WBApiError as exc:
    raise WBStockError(f"Не удалось обновить остаток в WB: {exc}") from exc
  return amount


def transfer_wb_stock_between_warehouses(
  seller: Seller,
  *,
  barcode: str,
  from_warehouse_id: int,
  to_warehouse_id: int,
  quantity: int,
) -> dict:
  """Переместить остаток между FBS-складами WB без изменения суммы."""
  if from_warehouse_id == to_warehouse_id:
    raise WBStockError("Выберите разные склады")
  if quantity <= 0:
    raise WBStockError("Количество должно быть больше 0")

  from_wh = get_seller_warehouse(seller, from_warehouse_id)
  to_wh = get_seller_warehouse(seller, to_warehouse_id)

  barcode = barcode.strip()
  from_amount = fetch_wb_stock_for_barcode(seller, from_wh, barcode)
  to_amount = fetch_wb_stock_for_barcode(seller, to_wh, barcode)

  if from_amount < quantity:
    raise WBStockError(
      f"На складе «{from_wh.name}» только {from_amount} шт., нельзя перенести {quantity}"
    )

  new_from = from_amount - quantity
  new_to = to_amount + quantity

  set_wb_stock_absolute(seller, from_wh, barcode, new_from)
  set_wb_stock_absolute(seller, to_wh, barcode, new_to)

  return {
    "barcode": barcode,
    "quantity": quantity,
    "from_warehouse": {
      "id": from_wh.id,
      "name": from_wh.name,
      "previous": from_amount,
      "new": new_from,
    },
    "to_warehouse": {
      "id": to_wh.id,
      "name": to_wh.name,
      "previous": to_amount,
      "new": new_to,
    },
    "total": new_from + new_to,
  }


def sync_product_warehouse_stocks_from_wb(seller, product) -> dict:
  """Обновить ProductWarehouseStock и Product.quantity из WB."""
  from apps.warehouse.models import ProductWarehouseStock

  stock_map = fetch_summed_wb_stocks(seller, [product.barcode])
  data = stock_map.get(product.barcode, {"total": 0, "by_warehouse": {}})
  warehouses = {wh.id: wh for wh in get_enabled_seller_warehouses(seller)}

  for wh_pk, qty in (data.get("by_warehouse") or {}).items():
    warehouse = warehouses.get(int(wh_pk))
    if not warehouse:
      continue
    ProductWarehouseStock.objects.update_or_create(
      product=product,
      seller_warehouse=warehouse,
      defaults={"quantity": max(0, int(qty))},
    )

  product.quantity = int(data.get("total") or 0)
  product.save(update_fields=["quantity", "updated_at"])
  return data
