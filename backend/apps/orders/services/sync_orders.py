import logging

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.integrations.models import AuditLog

logger = logging.getLogger(__name__)
from apps.integrations.wb_client import WBApiError, WBClient
from apps.integrations.wb_crypto import TokenCryptoError, decrypt_token
from apps.orders.models import Order
from apps.orders.services.sync_statuses import sync_order_statuses_for_seller
from apps.orders.services.wb_status import WB_SUPPLIER_NEW, apply_wb_status_to_order
from apps.sellers.models import Seller
from apps.sellers.services.sync_warehouses import WarehouseSyncError, sync_seller_warehouses
from apps.sellers.services.warehouse_filter import (
  is_warehouse_enabled,
  resolve_wb_order_warehouse_id,
)
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
  from apps.integrations.marketplace import WB as MARKETPLACE_WB
  from apps.warehouse.services.product_lookup import resolve_product_by_barcode

  return resolve_product_by_barcode(seller, MARKETPLACE_WB, barcode)


def _touch_order_warehouse(seller: Seller, wb_order) -> None:
  updates: dict = {}
  resolved_wh_id = resolve_wb_order_warehouse_id(
    seller,
    wb_order.warehouse_id,
    wb_order.office_id,
  )
  if resolved_wh_id is not None:
    updates["wb_warehouse_id"] = resolved_wh_id
  if wb_order.created_at is not None:
    updates["wb_created_at"] = wb_order.created_at
  if not updates:
    return
  Order.objects.filter(seller=seller, wb_order_id=wb_order.wb_order_id).update(**updates)


def _repair_orders_warehouse_ids(seller: Seller, wb_orders: list) -> int:
  """Проставить wb_warehouse_id заказам, пропущенным из‑за officeId вместо warehouseId."""
  if not wb_orders:
    return 0
  from apps.sellers.services.warehouse_filter import (
    get_enabled_wb_warehouse_ids,
    seller_has_warehouse_config,
  )

  by_id = {order.wb_order_id: order for order in wb_orders}
  qs = Order.objects.filter(seller=seller)
  if seller_has_warehouse_config(seller):
    enabled = get_enabled_wb_warehouse_ids(seller)
    qs = qs.filter(Q(wb_warehouse_id__isnull=True) | ~Q(wb_warehouse_id__in=enabled))
  fixed = 0
  now = timezone.now()
  for order in qs.only("id", "wb_order_id", "wb_warehouse_id"):
    wb_order = by_id.get(order.wb_order_id)
    if not wb_order:
      continue
    resolved = resolve_wb_order_warehouse_id(
      seller,
      wb_order.warehouse_id,
      wb_order.office_id,
    )
    if resolved is None or resolved == order.wb_warehouse_id:
      continue
    Order.objects.filter(pk=order.pk).update(wb_warehouse_id=resolved, updated_at=now)
    fixed += 1
  return fixed


def _backfill_orders_meta(seller: Seller, wb_orders: list) -> int:
  updated = 0
  for wb_order in wb_orders:
    updates: dict = {}
    resolved_wh_id = resolve_wb_order_warehouse_id(
      seller,
      wb_order.warehouse_id,
      wb_order.office_id,
    )
    if resolved_wh_id is not None:
      updates["wb_warehouse_id"] = resolved_wh_id
    if wb_order.created_at is not None:
      updates["wb_created_at"] = wb_order.created_at
    if not updates:
      continue
    count = Order.objects.filter(seller=seller, wb_order_id=wb_order.wb_order_id).update(**updates)
    updated += count
  return updated


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
    resolved_wh_id = resolve_wb_order_warehouse_id(
      seller,
      wb_order.warehouse_id,
      wb_order.office_id,
    )
    if not is_warehouse_enabled(seller, wb_order.warehouse_id, wb_order.office_id):
      skipped_warehouse += 1
      continue

    product = _link_product(seller, wb_order.barcode)
    defaults = {
      "seller": seller,
      "barcode": wb_order.barcode,
      "product": product,
      "wb_warehouse_id": resolved_wh_id,
    }
    if wb_order.created_at is not None:
      defaults["wb_created_at"] = wb_order.created_at
    if mark_as_new:
      defaults["wb_supplier_status"] = WB_SUPPLIER_NEW
    order, was_created = Order.objects.update_or_create(
      wb_order_id=wb_order.wb_order_id,
      defaults=defaults,
    )
    if mark_as_new:
      apply_wb_status_to_order(order, WB_SUPPLIER_NEW, order.wb_status or "")
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


def sync_delivery_scans_for_seller(seller: Seller, *, user=None) -> dict:
  """Быстрая синхронизация scanDt поставок для вкладки «В доставке»."""
  if not seller.is_active:
    raise SyncError("Селлер неактивен")

  token = _get_seller_token(seller)
  client = WBClient(token)

  from apps.orders.services.supply_sync import sync_supply_scan_dates
  from apps.orders.services.sync_statuses import (
    reconcile_individually_accepted_delivery_orders,
    reconcile_stale_delivery_orders,
  )

  supply_scan_result = {"supplies_scanned": 0, "orders_closed": 0}
  stale_after_supply = {"stale_delivery_cleared": 0}
  individual_after_supply = {"individually_accepted_closed": 0}
  scan_error = ""
  try:
    supply_scan_result = sync_supply_scan_dates(seller, client=client)
    stale_after_supply = reconcile_stale_delivery_orders(seller, client, {})
    individual_after_supply = reconcile_individually_accepted_delivery_orders(seller)
  except Exception as exc:
    scan_error = str(exc)
    logger.exception("delivery scan sync failed for seller_id=%s", seller.id)

  reconciled = (
    stale_after_supply.get("stale_delivery_cleared", 0)
    + individual_after_supply.get("individually_accepted_closed", 0)
  )

  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.WB_SYNC,
    message=(
      f"Синхронизация scanDt поставок: закрыто {supply_scan_result.get('orders_closed', 0)}"
    ),
    details={
      "supply_scan": supply_scan_result,
      "reconciled": reconciled,
      "sync_mode": "delivery",
      "scan_error": scan_error,
    },
  )

  return {
    "success": not scan_error,
    "sync_mode": "delivery",
    "supply_scan": supply_scan_result,
    "reconciled": reconciled,
    "scan_error": scan_error,
  }


def sync_orders_for_seller(seller: Seller, *, user=None, mode: str = "full") -> dict:
  if not seller.is_active:
    raise SyncError("Селлер неактивен")

  if mode == "delivery":
    return sync_delivery_scans_for_seller(seller, user=user)

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

  archive_import = {"created": 0, "updated": 0, "skipped_warehouse": 0, "raw_total": 0, "meta_backfill": 0}
  archive_orders = []
  delivery_supply_ids: set[int] = set()
  archive_days = 7 if quick else 30
  try:
    archive_result = client.fetch_recent_orders(days=archive_days)
    archive_orders = archive_result.orders
    archive_import = _import_wb_orders_atomic(seller, archive_orders, user=user)
    archive_import["raw_total"] = archive_result.raw_total
    archive_import["meta_backfill"] = _backfill_orders_meta(seller, archive_orders)
    archive_import["warehouse_repaired"] = _repair_orders_warehouse_ids(seller, archive_orders)
    created += archive_import["created"]
    updated += archive_import["updated"]
    skipped += archive_import["without_product"]
    skipped_warehouse += archive_import["skipped_warehouse"]
  except WBApiError:
    pass

  if quick:
    from apps.orders.services.supply_sync import delivery_order_ids_from_crm_pending

    delivery_supply_ids = delivery_order_ids_from_crm_pending(seller)
  else:
    try:
      delivery_supply_ids = client.fetch_delivery_order_ids()
    except WBApiError:
      delivery_supply_ids = set()

  supply_scan_result = {"supplies_scanned": 0, "orders_closed": 0}
  supply_sync_result = {}

  wb_orders = fetch_result.orders
  status_result = {"statuses_fetched": 0, "statuses_updated": 0, "reconciled": 0, "counts": {}}
  status_error = ""
  cancelled_in_supplies: list[dict] = []
  from apps.orders.services.wb_status import enabled_wb_new_order_ids_from_api

  new_wb_ids = enabled_wb_new_order_ids_from_api(seller, wb_orders)
  enabled_new_total = len(new_wb_ids)
  from apps.orders.services.supply_flow import (
    cancelled_orders_in_active_supplies,
    orders_at_risk_in_active_supplies,
  )

  at_risk_supply_order_ids = list(
    orders_at_risk_in_active_supplies(seller).values_list("id", flat=True)
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

  cancelled_in_supplies = cancelled_orders_in_active_supplies(
    seller,
    at_risk_supply_order_ids,
  )

  stale_after_supply = {"stale_delivery_cleared": 0}
  individual_after_supply = {"individually_accepted_closed": 0}
  try:
    from apps.orders.services.supply_sync import sync_supplies_from_wb, sync_supply_scan_dates
    from apps.orders.services.sync_statuses import (
      reconcile_individually_accepted_delivery_orders,
      reconcile_stale_delivery_orders,
    )

    supply_scan_result = sync_supply_scan_dates(seller, client=client)
    supply_sync_result = sync_supplies_from_wb(seller, include_closed=True)
    # Повторно: sync_supplies мог откатить заказы, если в списке WB не было scanDt
    rescan = sync_supply_scan_dates(seller, client=client)
    supply_scan_result["supplies_scanned"] += int(rescan.get("supplies_scanned") or 0)
    supply_scan_result["orders_closed"] += int(rescan.get("orders_closed") or 0)
    supply_scan_result["rescan"] = rescan
    stale_after_supply = reconcile_stale_delivery_orders(seller, client, {})
    individual_after_supply = reconcile_individually_accepted_delivery_orders(seller)
  except Exception:
    logger.exception("supply sync failed for seller_id=%s", seller.id)

  reconciled = status_result.get("reconciled", 0)
  reconciled += stale_after_supply.get("stale_delivery_cleared", 0)
  reconciled += individual_after_supply.get("individually_accepted_closed", 0)

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
      "supply_sync": supply_sync_result,
      "supply_scan": supply_scan_result,
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
      "cancelled_in_supplies": cancelled_in_supplies,
      "synced_at": timezone.now().isoformat(),
      "sync_mode": mode,
    },
  )

  from apps.warehouse.services.product_lookup import relink_orders_to_products_for_seller

  orders_relinked = relink_orders_to_products_for_seller(seller)

  return {
    "seller_id": seller.id,
    "sync_mode": mode,
    "orders_relinked": orders_relinked,
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
    "cancelled_in_supplies": cancelled_in_supplies,
    "supply_sync": supply_sync_result,
    "supply_scan": supply_scan_result,
  }


def sync_all_delivery_scans(*, user=None, fulfillment=None) -> dict:
  """Быстрая синхронизация scanDt для всех активных селлеров WB."""
  sellers = Seller.objects.filter(is_active=True, wb_enabled=True).exclude(
    wb_api_token_encrypted="",
  )
  if fulfillment:
    sellers = sellers.filter(fulfillment=fulfillment)

  results = []
  errors = []
  totals = {"supplies_scanned": 0, "orders_closed": 0, "reconciled": 0}

  for seller in sellers:
    try:
      stats = sync_delivery_scans_for_seller(seller, user=user)
      results.append({"seller_id": seller.id, **stats})
      scan = stats.get("supply_scan") or {}
      totals["supplies_scanned"] += int(scan.get("supplies_scanned") or 0)
      totals["orders_closed"] += int(scan.get("orders_closed") or 0)
      totals["reconciled"] += int(stats.get("reconciled") or 0)
    except SyncError as exc:
      errors.append({"seller_id": seller.id, "error": str(exc)})

  return {"results": results, "errors": errors, "totals": totals}


def sync_all_active_sellers(*, user=None, mode: str = "full", fulfillment=None) -> list[dict]:
  results = []
  errors = []
  sellers = Seller.objects.filter(is_active=True)
  if fulfillment:
    sellers = sellers.filter(fulfillment=fulfillment)
  for seller in sellers:
    try:
      results.append(sync_orders_for_seller(seller, user=user, mode=mode))
    except SyncError as exc:
      errors.append({"seller_id": seller.id, "error": str(exc)})
  return {"results": results, "errors": errors}
