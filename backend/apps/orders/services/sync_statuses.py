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
  WB_IN_DELIVERY_WB_STATUSES,
  WB_SUPPLIER_DELIVERY,
  apply_wb_status_to_order,
  compute_live_wb_counts,
  is_wb_in_delivery,
  wb_in_delivery_q,
  save_wb_counts_to_seller,
)
from apps.sellers.models import Seller
from apps.sellers.services.warehouse_filter import filter_orders_for_seller

SYNC_VERSION = "delivery-v8"


def _delivery_status_breakdown(status_map: dict[int, dict]) -> dict[str, int]:
  breakdown: dict[str, int] = {}
  for item in status_map.values():
    if (item.get("supplierStatus") or "").strip() != WB_SUPPLIER_DELIVERY:
      continue
    wb = (item.get("wbStatus") or "").strip() or "(empty)"
    breakdown[wb] = breakdown.get(wb, 0) + 1
  return breakdown


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


def reconcile_wb_orders_for_seller(
  seller: Seller,
  status_map: dict[int, dict],
  *,
  user=None,
) -> dict:
  """Сверка: отмены и выкуп — в SHIPPED/CANCELLED; sorted/waiting остаются в доставке."""
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

  restored_in_delivery = Order.objects.filter(
    seller=seller,
    wb_supplier_status=WB_SUPPLIER_DELIVERY,
    wb_status__in=WB_IN_DELIVERY_WB_STATUSES,
    status=Order.Status.SHIPPED,
  ).update(status=Order.Status.IN_DELIVERY, updated_at=now)

  shipped_missing = 0
  if missing_ids:
    shipped_missing = Order.objects.filter(
      seller=seller,
      wb_order_id__in=missing_ids,
    ).exclude(status=Order.Status.SHIPPED).update(status=Order.Status.SHIPPED, updated_at=now)

  result = {
    "cancelled_terminal": cancelled_terminal,
    "shipped_delivered": shipped_delivered,
    "restored_in_delivery": restored_in_delivery,
    "shipped_missing": shipped_missing,
    "missing_from_api": len(missing_ids),
    "delivery_status_breakdown": _delivery_status_breakdown(status_map),
  }

  reconciled = sum(result[k] for k in (
    "cancelled_terminal", "shipped_delivered", "restored_in_delivery", "shipped_missing",
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
) -> dict:
  wb_ids = list(
    filter_orders_for_seller(Order.objects.filter(seller=seller), seller).values_list(
      "wb_order_id",
      flat=True,
    )
  )
  if not wb_ids:
    counts = {"new": 0, "in_picking": 0, "in_delivery": 0, "cancelled": 0}
    save_wb_counts_to_seller(seller, counts)
    return {"statuses_fetched": 0, "statuses_updated": 0, "reconciled": 0, "counts": counts}

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

  updated = _apply_statuses_to_orders(seller, status_map)
  reconcile = reconcile_wb_orders_for_seller(seller, status_map, user=user)
  reconciled = sum(reconcile.get(k, 0) for k in (
    "cancelled_terminal", "shipped_delivered", "restored_in_delivery", "shipped_missing",
  ))

  live_counts = compute_live_wb_counts(status_map, allowed_ids=set(wb_ids))
  if new_orders_total > 0:
    live_counts["new"] = new_orders_total

  counts = get_seller_stage_counts(seller)
  save_wb_counts_to_seller(seller, counts)

  return {
    "sync_version": SYNC_VERSION,
    "statuses_fetched": len(status_map),
    "statuses_updated": updated,
    "reconciled": reconciled,
    "live_counts": live_counts,
    "delivery_breakdown": reconcile.get("delivery_status_breakdown", {}),
    "reconcile": reconcile,
    "counts": counts,
  }
