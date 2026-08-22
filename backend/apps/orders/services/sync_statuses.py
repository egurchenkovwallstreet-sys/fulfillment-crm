from django.db.models import Q
from django.utils import timezone

from apps.integrations.models import AuditLog
from apps.integrations.wb_client import WBApiError, WBClient, WBOrderData
from apps.orders.models import Order
from apps.orders.services.assembly import get_seller_stage_counts
from apps.orders.services.wb_status import (
  CANCEL_SUPPLIER_STATUSES,
  CANCEL_WB_STATUSES,
  WB_DELIVERED_WB_STATUSES,
  WB_DELIVERY_TAB_WB_STATUS,
  WB_SUPPLIER_DELIVERY,
  WB_SUPPLIER_NEW,
  WB_TERMINAL_WB_STATUSES,
  apply_wb_status_to_order,
  compute_live_wb_counts,
  is_wb_in_delivery,
  save_wb_counts_to_seller,
)
from apps.sellers.models import Seller
from apps.sellers.services.warehouse_filter import (
  filter_orders_for_seller,
  is_warehouse_enabled,
)

SYNC_VERSION = "delivery-v11"

# warehouse_id по wb_order_id — для фильтра при подсчёте live-счётчиков
WarehouseMap = dict[int, int | None]


def _delivery_status_breakdown(status_map: dict[int, dict]) -> dict[str, int]:
  breakdown: dict[str, int] = {}
  for item in status_map.values():
    if (item.get("supplierStatus") or "").strip() != WB_SUPPLIER_DELIVERY:
      continue
    wb = (item.get("wbStatus") or "").strip() or "(empty)"
    breakdown[wb] = breakdown.get(wb, 0) + 1
  return breakdown


def _build_warehouse_map(
  seller: Seller,
  archive_orders: list[WBOrderData] | None,
) -> WarehouseMap:
  warehouse_map: WarehouseMap = {}
  for row in Order.objects.filter(seller=seller).values("wb_order_id", "wb_warehouse_id"):
    warehouse_map[int(row["wb_order_id"])] = row["wb_warehouse_id"]
  if archive_orders:
    for order in archive_orders:
      warehouse_map.setdefault(order.wb_order_id, order.warehouse_id)
  return warehouse_map


def _collect_poll_order_ids(
  seller: Seller,
  *,
  archive_orders: list[WBOrderData] | None = None,
  delivery_supply_ids: set[int] | None = None,
) -> set[int]:
  """Все ID для POST /orders/status — БД + архив WB + поставки в доставке."""
  poll_ids = set(
    filter_orders_for_seller(Order.objects.filter(seller=seller), seller).values_list(
      "wb_order_id",
      flat=True,
    )
  )
  if archive_orders:
    for order in archive_orders:
      if is_warehouse_enabled(seller, order.warehouse_id):
        poll_ids.add(order.wb_order_id)
  if delivery_supply_ids:
    poll_ids.update(delivery_supply_ids)
  return poll_ids


def _scoped_order_ids(poll_ids: set[int], warehouse_map: WarehouseMap, seller: Seller) -> set[int]:
  scoped: set[int] = set()
  for order_id in poll_ids:
    if is_warehouse_enabled(seller, warehouse_map.get(order_id)):
      scoped.add(order_id)
  return scoped


def _apply_statuses_to_orders(seller: Seller, status_map: dict[int, dict]) -> int:
  updated = 0
  orders_qs = filter_orders_for_seller(Order.objects.filter(seller=seller), seller)
  for order in orders_qs:
    data = status_map.get(order.wb_order_id)
    if not data:
      continue
    supplier = (data.get("supplierStatus") or "").strip()
    wb = (data.get("wbStatus") or "").strip()
    if apply_wb_status_to_order(order, supplier, wb):
      updated += 1
  return updated


def _mark_confirmed_new_orders(seller: Seller, new_wb_ids: set[int]) -> int:
  """Заказы из GET /orders/new — supplierStatus new в CRM."""
  if not new_wb_ids:
    return 0
  now = timezone.now()
  return (
    filter_orders_for_seller(
      Order.objects.filter(seller=seller, wb_order_id__in=new_wb_ids),
      seller,
    )
    .exclude(wb_supplier_status=WB_SUPPLIER_NEW)
    .update(wb_supplier_status=WB_SUPPLIER_NEW, updated_at=now)
  )


def reconcile_stale_new_orders(
  seller: Seller,
  client: WBClient,
  new_wb_ids: set[int],
  status_map: dict[int, dict],
) -> dict:
  """
  Снять «новый» с заказов, которых нет в GET /api/v3/orders/new.
  Именно из-за рассинхрона здесь список сборки показывал больше строк, чем счётчик WB.
  """
  stale_qs = filter_orders_for_seller(
    Order.objects.filter(seller=seller)
    .filter(Q(wb_supplier_status=WB_SUPPLIER_NEW) | Q(wb_supplier_status=""))
    .exclude(status__in=[Order.Status.CANCELLED, Order.Status.SHIPPED]),
    seller,
  ).exclude(wb_order_id__in=new_wb_ids)

  stale_orders = list(stale_qs)
  if not stale_orders:
    return {"stale_new_cleared": 0, "new_marked": 0}

  missing_ids = [order.wb_order_id for order in stale_orders if order.wb_order_id not in status_map]
  if missing_ids:
    try:
      for item in client.fetch_order_statuses(missing_ids):
        oid = item.get("id")
        if oid is not None:
          status_map[int(oid)] = item
    except WBApiError:
      pass

  cleared = 0
  now = timezone.now()
  for order in stale_orders:
    data = status_map.get(order.wb_order_id)
    if data:
      supplier = (data.get("supplierStatus") or "").strip()
      wb = (data.get("wbStatus") or "").strip()
      if supplier != WB_SUPPLIER_NEW:
        if apply_wb_status_to_order(order, supplier, wb):
          cleared += 1
      continue

    order.wb_supplier_status = WB_SUPPLIER_DELIVERY
    order.wb_status = "sorted"
    order.status = Order.Status.SHIPPED
    order.save(update_fields=["wb_supplier_status", "status", "updated_at"])
    cleared += 1

  new_marked = _mark_confirmed_new_orders(seller, new_wb_ids)
  return {"stale_new_cleared": cleared, "new_marked": new_marked}


def reconcile_wb_orders_for_seller(
  seller: Seller,
  status_map: dict[int, dict],
  *,
  user=None,
) -> dict:
  """Сверка: отмены/выкуп → SHIPPED/CANCELLED; sorted и пр. — не «В доставке»."""
  now = timezone.now()
  wb_ids_in_db = set(
    Order.objects.filter(seller=seller).values_list("wb_order_id", flat=True)
  )
  missing_ids = wb_ids_in_db - set(status_map.keys())

  cancelled_terminal = Order.objects.filter(seller=seller).filter(
    Q(wb_supplier_status__in=CANCEL_SUPPLIER_STATUSES) | Q(wb_status__in=CANCEL_WB_STATUSES)
  ).exclude(status=Order.Status.CANCELLED).update(status=Order.Status.CANCELLED, updated_at=now)

  shipped_delivered = Order.objects.filter(
    seller=seller,
    wb_status__in=WB_DELIVERED_WB_STATUSES,
  ).exclude(status=Order.Status.SHIPPED).update(status=Order.Status.SHIPPED, updated_at=now)

  shipped_not_waiting = Order.objects.filter(
    seller=seller,
    wb_supplier_status=WB_SUPPLIER_DELIVERY,
  ).exclude(wb_status=WB_DELIVERY_TAB_WB_STATUS).exclude(
    wb_status__in=WB_TERMINAL_WB_STATUSES,
  ).exclude(wb_status="").exclude(
    status__in=[Order.Status.SHIPPED, Order.Status.CANCELLED],
  ).update(status=Order.Status.SHIPPED, updated_at=now)

  shipped_missing = 0
  if missing_ids:
    shipped_missing = Order.objects.filter(
      seller=seller,
      wb_order_id__in=missing_ids,
    ).exclude(status=Order.Status.SHIPPED).update(status=Order.Status.SHIPPED, updated_at=now)

  delivery_waiting = sum(
    1
    for item in status_map.values()
    if is_wb_in_delivery(
      (item.get("supplierStatus") or "").strip(),
      (item.get("wbStatus") or "").strip(),
    )
  )

  result = {
    "cancelled_terminal": cancelled_terminal,
    "shipped_delivered": shipped_delivered,
    "shipped_not_waiting": shipped_not_waiting,
    "shipped_missing": shipped_missing,
    "missing_from_api": len(missing_ids),
    "delivery_waiting_in_status_map": delivery_waiting,
    "delivery_status_breakdown": _delivery_status_breakdown(status_map),
  }

  reconciled = sum(result[k] for k in (
    "cancelled_terminal", "shipped_delivered", "shipped_not_waiting", "shipped_missing",
  ))
  if reconciled:
    AuditLog.objects.create(
      user=user,
      seller=seller,
      action_type=AuditLog.ActionType.WB_SYNC,
      message=f"Сверка WB ({SYNC_VERSION}): убрано {reconciled}",
      details=result,
    )

  return result


def sync_order_statuses_for_seller(
  seller: Seller,
  client: WBClient,
  *,
  user=None,
  new_wb_ids: list[int] | None = None,
  new_orders_total: int = 0,
  archive_orders: list[WBOrderData] | None = None,
  delivery_supply_ids: set[int] | None = None,
) -> dict:
  warehouse_map = _build_warehouse_map(seller, archive_orders)
  poll_ids = _collect_poll_order_ids(
    seller,
    archive_orders=archive_orders,
    delivery_supply_ids=delivery_supply_ids,
  )
  scoped_ids = _scoped_order_ids(poll_ids, warehouse_map, seller)

  if not poll_ids:
    counts = {"new": 0, "in_picking": 0, "in_delivery": 0, "cancelled": 0}
    save_wb_counts_to_seller(seller, counts)
    return {"statuses_fetched": 0, "statuses_updated": 0, "reconciled": 0, "counts": counts}

  try:
    wb_statuses = client.fetch_order_statuses(list(poll_ids))
  except WBApiError as exc:
    AuditLog.objects.create(
      user=user,
      seller=seller,
      action_type=AuditLog.ActionType.API_ERROR,
      message=f"Ошибка получения статусов WB: {exc}",
      details={"status_code": exc.status_code},
    )
    raise

  status_map = {
    int(item["id"]): item
    for item in wb_statuses
    if item.get("id") is not None
  }

  updated = _apply_statuses_to_orders(seller, status_map)
  reconcile = reconcile_wb_orders_for_seller(seller, status_map, user=user)
  reconciled = sum(reconcile.get(k, 0) for k in (
    "cancelled_terminal", "shipped_delivered", "shipped_not_waiting", "shipped_missing",
  ))

  new_ids_set = set(new_wb_ids or [])
  stale_new = reconcile_stale_new_orders(seller, client, new_ids_set, status_map)
  reconciled += stale_new.get("stale_new_cleared", 0)

  live_counts = compute_live_wb_counts(status_map, allowed_ids=scoped_ids)
  if new_orders_total > 0:
    live_counts["new"] = new_orders_total
  elif new_wb_ids is not None:
    live_counts["new"] = len(new_ids_set & scoped_ids)

  save_wb_counts_to_seller(seller, live_counts)
  db_counts = get_seller_stage_counts(seller)

  return {
    "sync_version": SYNC_VERSION,
    "statuses_fetched": len(status_map),
    "statuses_polled": len(poll_ids),
    "statuses_scoped": len(scoped_ids),
    "statuses_updated": updated,
    "reconciled": reconciled,
    "stale_new": stale_new,
    "live_counts": live_counts,
    "delivery_breakdown": reconcile.get("delivery_status_breakdown", {}),
    "delivery_waiting_raw": reconcile.get("delivery_waiting_in_status_map"),
    "reconcile": reconcile,
    "counts": live_counts,
    "db_counts": db_counts,
  }
