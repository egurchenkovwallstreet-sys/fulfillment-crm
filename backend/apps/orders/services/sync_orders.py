from django.db import transaction
from django.utils import timezone

from apps.integrations.models import AuditLog
from apps.integrations.wb_client import WBApiError, WBClient
from apps.integrations.wb_crypto import TokenCryptoError, decrypt_token
from apps.orders.models import Order
from apps.orders.services.sync_statuses import sync_order_statuses_for_seller
from apps.orders.services.wb_status import WB_SUPPLIER_NEW
from apps.sellers.models import Seller
from apps.sellers.services.sync_warehouses import WarehouseSyncError, sync_seller_warehouses
from apps.sellers.services.warehouse_filter import is_warehouse_enabled
from apps.warehouse.models import Product


class SyncError(Exception):
  pass


def _get_seller_token(seller: Seller) -> str:
  if not seller.wb_api_token_encrypted:
    raise SyncError(f"У селлера «{seller.company_name}» не задан токен WB")
  try:
    return decrypt_token(seller.wb_api_token_encrypted)
  except TokenCryptoError as exc:
    raise SyncError(str(exc)) from exc


def _link_product(seller: Seller, barcode: str) -> Product | None:
  return Product.objects.filter(seller=seller, barcode=barcode).first()


def _import_wb_orders(
  seller: Seller,
  wb_orders: list,
  *,
  mark_as_new: bool = False,
  user=None,
) -> dict:
  created = 0
  updated = 0
  skipped = 0
  skipped_warehouse = 0

  for wb_order in wb_orders:
    if not is_warehouse_enabled(seller, wb_order.warehouse_id):
      skipped_warehouse += 1
      continue

    product = _link_product(seller, wb_order.barcode)
    defaults = {
      "seller": seller,
      "barcode": wb_order.barcode,
      "product": product,
      "wb_warehouse_id": wb_order.warehouse_id,
    }
    if mark_as_new:
      defaults["wb_supplier_status"] = WB_SUPPLIER_NEW
    order, was_created = Order.objects.update_or_create(
      wb_order_id=wb_order.wb_order_id,
      defaults=defaults,
    )
    if was_created:
      created += 1
    else:
      updated += 1
    if not product:
      skipped += 1

  return {
    "created": created,
    "updated": updated,
    "without_product": skipped,
    "skipped_warehouse": skipped_warehouse,
  }


@transaction.atomic
def _import_wb_orders_atomic(seller, wb_orders, *, mark_as_new=False, user=None):
  return _import_wb_orders(seller, wb_orders, mark_as_new=mark_as_new, user=user)


def sync_orders_for_seller(seller: Seller, *, user=None, mode: str = "full") -> dict:
  if not seller.is_active:
    raise SyncError("Селлер неактивен")

  quick = mode == "quick"
  token = _get_seller_token(seller)
  client = WBClient(token)

  warehouse_sync_error = ""
  if not quick:
    try:
      sync_seller_warehouses(seller, user=user)
    except WarehouseSyncError as exc:
      warehouse_sync_error = str(exc)

  try:
    fetch_result = client.fetch_new_orders()
  except WBApiError as exc:
    AuditLog.objects.create(
      user=user,
      seller=seller,
      action_type=AuditLog.ActionType.API_ERROR,
      message=f"Ошибка синхронизации заказов WB: {exc}",
      details={"status_code": exc.status_code},
    )
    raise SyncError(str(exc)) from exc

  new_import = _import_wb_orders_atomic(seller, fetch_result.orders, mark_as_new=True, user=user)
  created = new_import["created"]
  updated = new_import["updated"]
  skipped = new_import["without_product"]
  skipped_warehouse = new_import["skipped_warehouse"]

  archive_import = {"created": 0, "updated": 0, "skipped_warehouse": 0, "raw_total": 0}
  archive_orders = []
  delivery_supply_ids: set[int] = set()
  if not quick:
    try:
      archive_result = client.fetch_recent_orders(days=30)
      archive_orders = archive_result.orders
      archive_import = _import_wb_orders_atomic(seller, archive_orders, user=user)
      archive_import["raw_total"] = archive_result.raw_total
      created += archive_import["created"]
      updated += archive_import["updated"]
      skipped += archive_import["without_product"]
      skipped_warehouse += archive_import["skipped_warehouse"]
    except WBApiError:
      pass

  try:
    delivery_supply_ids = client.fetch_delivery_order_ids()
  except WBApiError:
    pass

  wb_orders = fetch_result.orders
  status_result = {"statuses_fetched": 0, "statuses_updated": 0, "reconciled": 0, "counts": {}}
  status_error = ""
  new_wb_ids = [wb_order.wb_order_id for wb_order in wb_orders if is_warehouse_enabled(seller, wb_order.warehouse_id)]
  enabled_new_total = sum(
    1 for wb_order in wb_orders if is_warehouse_enabled(seller, wb_order.warehouse_id)
  )
  try:
    status_result = sync_order_statuses_for_seller(
      seller,
      client,
      user=user,
      new_wb_ids=new_wb_ids,
      new_orders_total=enabled_new_total,
      archive_orders=archive_orders,
      delivery_supply_ids=delivery_supply_ids,
      quick=quick,
    )
  except WBApiError as exc:
    status_error = str(exc)

  reconciled = status_result.get("reconciled", 0)

  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.WB_SYNC,
    message=(
      f"Синхронизация заказов WB: +{created}, обновлено {updated}, "
      f"из WB {fetch_result.raw_total}"
    ),
    details={
      "created": created,
      "updated": updated,
      "without_product": skipped,
      "skipped_no_barcode": fetch_result.skipped_no_barcode,
      "skipped_warehouse": skipped_warehouse,
      "archive_backfill": archive_import,
      "delivery_supply_orders": len(delivery_supply_ids),
      "warehouse_sync_error": warehouse_sync_error,
      "fetched": len(wb_orders),
      "raw_total": fetch_result.raw_total,
      "pages": fetch_result.pages,
      "statuses_fetched": status_result["statuses_fetched"],
      "statuses_updated": status_result["statuses_updated"],
      "reconciled": reconciled,
      "sync_version": status_result.get("sync_version"),
      "status_error": status_error,
      "wb_counts": status_result.get("counts", {}),
      "live_counts": status_result.get("live_counts", {}),
      "delivery_all": status_result.get("delivery_all"),
      "delivery_recent": status_result.get("delivery_recent"),
      "delivery_breakdown": status_result.get("delivery_breakdown"),
      "reconcile": status_result.get("reconcile", {}),
      "synced_at": timezone.now().isoformat(),
      "sync_mode": mode,
    },
  )

  return {
    "seller_id": seller.id,
    "sync_mode": mode,
    "created": created,
    "updated": updated,
    "without_product": skipped,
    "fetched": len(wb_orders),
    "raw_total": fetch_result.raw_total,
    "skipped_no_barcode": fetch_result.skipped_no_barcode,
    "skipped_warehouse": skipped_warehouse,
    "archive_backfill": archive_import,
    "warehouse_sync_error": warehouse_sync_error,
    "pages": fetch_result.pages,
    "statuses_fetched": status_result["statuses_fetched"],
    "statuses_updated": status_result["statuses_updated"],
    "reconciled": reconciled,
    "sync_version": status_result.get("sync_version"),
    "status_error": status_error,
    "wb_counts": status_result.get("counts", {}),
    "live_counts": status_result.get("live_counts", {}),
    "delivery_all": status_result.get("delivery_all"),
    "delivery_recent": status_result.get("delivery_recent"),
    "delivery_breakdown": status_result.get("delivery_breakdown"),
    "reconcile": status_result.get("reconcile", {}),
  }


def sync_all_active_sellers(*, user=None, mode: str = "full") -> list[dict]:
  results = []
  errors = []
  for seller in Seller.objects.filter(is_active=True):
    try:
      results.append(sync_orders_for_seller(seller, user=user, mode=mode))
    except SyncError as exc:
      errors.append({"seller_id": seller.id, "error": str(exc)})
  return {"results": results, "errors": errors}
