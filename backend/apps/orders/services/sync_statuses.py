from django.db.models import Q
from django.utils import timezone

from apps.integrations.models import AuditLog
from apps.integrations.wb_client import WBApiError, WBClient
from apps.orders.models import Order
from apps.orders.services.assembly import get_seller_stage_counts
from apps.orders.services.wb_status import (
  CANCEL_SUPPLIER_STATUSES,
  CANCEL_WB_STATUSES,
  WB_DELIVERED_WB_STATUSES,
  WB_SUPPLIER_DELIVERY,
  WB_TERMINAL_WB_STATUSES,
  apply_wb_status_to_order,
  compute_live_wb_counts,
  is_wb_in_delivery,
  wb_in_delivery_q,
  save_wb_counts_to_seller,
)
from apps.sellers.models import Seller

# Как вкладка «В доставке» в ЛК WB — только заказы за последние N дней
DELIVERY_COUNT_DAYS = 5


def _count_delivery_all(status_map: dict[int, dict]) -> int:
  return sum(
    1
    for item in status_map.values()
    if is_wb_in_delivery(
      (item.get("supplierStatus") or "").strip(),
      (item.get("wbStatus") or "").strip(),
    )
  )


def _apply_statuses_to_orders(seller: Seller, status_map: dict[int, dict]) -> int:
  updated = 0
  for order in Order.objects.filter(seller=seller):
    data = status_map.get(order.wb_order_id)
    if not data:
      continue
    supplier = (data.get("supplierStatus") or "").strip()
    wb = (data.get("wbStatus") or "").strip()
    if apply_wb_status_to_order(order, supplier, wb):
      updated += 1
  return updated


def _delivery_count_from_db(seller: Seller, recent_ids: set[int]) -> int:
  """Счёт «В доставке» из БД после reconcile — без выкупа, отмен и архива."""
  qs = Order.objects.filter(seller=seller).filter(wb_in_delivery_q())
  if recent_ids:
    qs = qs.filter(wb_order_id__in=recent_ids)
  return qs.count()


def reconcile_wb_orders_for_seller(
  seller: Seller,
  status_map: dict[int, dict],
  recent_ids: set[int],
  *,
  user=None,
) -> dict:
  """Снять с «В доставке» выкупленные, отменённые, отказы и архивные заказы."""
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

  shipped_missing = 0
  if missing_ids:
    shipped_missing = Order.objects.filter(
      seller=seller,
      wb_order_id__in=missing_ids,
    ).exclude(status=Order.Status.SHIPPED).update(status=Order.Status.SHIPPED, updated_at=now)

  shipped_stale = 0
  if recent_ids:
    shipped_stale = Order.objects.filter(
      seller=seller,
      wb_supplier_status=WB_SUPPLIER_DELIVERY,
    ).exclude(wb_order_id__in=recent_ids).exclude(
      wb_status__in=WB_TERMINAL_WB_STATUSES | frozenset({"waiting"}),
    ).exclude(wb_status="").exclude(
      status__in=[Order.Status.SHIPPED, Order.Status.CANCELLED],
    ).update(status=Order.Status.SHIPPED, updated_at=now)

  result = {
    "cancelled_terminal": cancelled_terminal,
    "shipped_delivered": shipped_delivered,
    "shipped_missing": shipped_missing,
    "shipped_stale": shipped_stale,
    "missing_from_api": len(missing_ids),
    "delivery_window_days": DELIVERY_COUNT_DAYS,
    "recent_order_ids": len(recent_ids),
  }

  if any(result[k] for k in ("cancelled_terminal", "shipped_delivered", "shipped_missing", "shipped_stale")):
    AuditLog.objects.create(
      user=user,
      seller=seller,
      action_type=AuditLog.ActionType.WB_SYNC,
      message=(
        f"Сверка статусов WB: отменено {cancelled_terminal}, "
        f"завершено {shipped_delivered + shipped_missing + shipped_stale}"
      ),
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
) -> dict:
  """Запросить статусы WB, обновить заказы и сохранить счётчики."""
  wb_ids = list(
    Order.objects.filter(seller=seller).values_list("wb_order_id", flat=True)
  )
  if not wb_ids:
    counts = {"new": 0, "in_picking": 0, "in_delivery": 0, "cancelled": 0}
    save_wb_counts_to_seller(seller, counts)
    return {"statuses_fetched": 0, "statuses_updated": 0, "counts": counts}

  try:
    wb_statuses = client.fetch_order_statuses(wb_ids)
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

  try:
    recent_ids = client.fetch_recent_order_ids(days=DELIVERY_COUNT_DAYS)
  except WBApiError:
    recent_ids = set()

  delivery_ids = recent_ids | set(new_wb_ids or [])

  updated = _apply_statuses_to_orders(seller, status_map)
  reconcile = reconcile_wb_orders_for_seller(seller, status_map, recent_ids, user=user)

  delivery_all = _count_delivery_all(status_map)
  live_counts = compute_live_wb_counts(status_map, delivery_wb_ids=delivery_ids)
  live_counts["in_delivery"] = _delivery_count_from_db(seller, recent_ids)
  if new_orders_total > 0:
    live_counts["new"] = new_orders_total
  save_wb_counts_to_seller(seller, live_counts)
  counts = get_seller_stage_counts(seller)

  return {
    "statuses_fetched": len(status_map),
    "statuses_updated": updated,
    "live_counts": live_counts,
    "delivery_all": delivery_all,
    "delivery_recent": live_counts["in_delivery"],
    "reconcile": reconcile,
    "counts": counts,
  }
