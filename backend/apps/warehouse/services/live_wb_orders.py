"""Счётчики заказов WB по API (не из устаревшего кэша CRM)."""
from __future__ import annotations

from apps.integrations.marketplace import WB
from apps.integrations.wb_client import WBApiError, WBClient
from apps.integrations.wb_crypto import TokenCryptoError, decrypt_token
from apps.orders.services.supply_flow import picking_stage_orders_queryset
from apps.orders.services.wb_status import WB_SUPPLIER_ASSEMBLY
from apps.sellers.models import Seller, SellerWarehouse
from apps.warehouse.services.catalog_fetch import barcode_lookup_variants, normalize_barcode
from apps.warehouse.services.wb_stocks import WBStockError


class LiveWbOrdersError(Exception):
  pass


def _wb_client(seller: Seller) -> WBClient:
  if not seller.wb_api_token_encrypted:
    raise LiveWbOrdersError(f"У селлера «{seller.company_name}» не задан токен WB")
  try:
    token = decrypt_token(seller.wb_api_token_encrypted)
  except TokenCryptoError as exc:
    raise LiveWbOrdersError(str(exc)) from exc
  return WBClient(token)


def _barcode_variant_set(barcode: str) -> set[str]:
  variants: set[str] = set()
  for variant in barcode_lookup_variants(barcode, WB):
    code = normalize_barcode(variant)
    if code:
      variants.add(code)
  return variants


def _warehouse_match_ids(warehouse: SellerWarehouse) -> set[int]:
  ids = {int(warehouse.wb_warehouse_id)}
  if warehouse.office_id:
    ids.add(int(warehouse.office_id))
  return ids


def _order_on_warehouse(*, warehouse_id: int | None, office_id: int | None, warehouse: SellerWarehouse) -> bool:
  match_ids = _warehouse_match_ids(warehouse)
  if warehouse_id is not None and int(warehouse_id) in match_ids:
    return True
  if office_id is not None and int(office_id) in match_ids:
    return True
  return False


def count_live_new_orders_for_barcode_on_warehouse(
  seller: Seller,
  barcode: str,
  warehouse: SellerWarehouse,
) -> int:
  """Заказы «Новые» из GET /api/v3/orders/new по баркоду и складу."""
  client = _wb_client(seller)
  variants = _barcode_variant_set(barcode)
  if not variants:
    return 0
  try:
    fetch_result = client.fetch_new_orders()
  except WBApiError as exc:
    raise LiveWbOrdersError(str(exc)) from exc

  count = 0
  for order in fetch_result.orders:
    if not _order_on_warehouse(
      warehouse_id=order.warehouse_id,
      office_id=order.office_id,
      warehouse=warehouse,
    ):
      continue
    code = normalize_barcode(order.barcode or "")
    if code in variants:
      count += 1
  return count


def count_live_picking_orders_for_barcode_on_warehouse(
  seller: Seller,
  barcode: str,
  warehouse: SellerWarehouse,
) -> int:
  """Заказы «На сборке» — статусы через API для заказов CRM на этом складе."""
  variants = _barcode_variant_set(barcode)
  if not variants:
    return 0

  wb_wh = int(warehouse.wb_warehouse_id)
  qs = picking_stage_orders_queryset(seller).filter(
    wb_warehouse_id=wb_wh,
    barcode__in=variants,
  )
  order_ids = list(qs.values_list("wb_order_id", flat=True)[:1000])
  if not order_ids:
    return 0

  client = _wb_client(seller)
  try:
    statuses = client.fetch_order_statuses(order_ids)
  except WBApiError as exc:
    raise LiveWbOrdersError(str(exc)) from exc

  confirmed_ids: set[int] = set()
  for item in statuses:
    if not isinstance(item, dict):
      continue
    supplier = (item.get("supplierStatus") or "").strip()
    if supplier != WB_SUPPLIER_ASSEMBLY:
      continue
    raw_id = item.get("id") or item.get("orderId")
    try:
      confirmed_ids.add(int(raw_id))
    except (TypeError, ValueError):
      continue

  if not confirmed_ids:
    return 0

  return qs.filter(wb_order_id__in=confirmed_ids).count()


def count_live_open_orders_for_barcode_on_warehouse(
  seller: Seller,
  barcode: str,
  warehouse: SellerWarehouse,
) -> tuple[int, int, int]:
  """(новые, на сборке, всего) по API."""
  new_count = count_live_new_orders_for_barcode_on_warehouse(seller, barcode, warehouse)
  picking_count = count_live_picking_orders_for_barcode_on_warehouse(seller, barcode, warehouse)
  return new_count, picking_count, new_count + picking_count


def live_open_orders_error_as_wb_stock(exc: Exception) -> WBStockError:
  if isinstance(exc, LiveWbOrdersError):
    return WBStockError(str(exc))
  return WBStockError(str(exc))
