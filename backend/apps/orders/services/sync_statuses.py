from django.utils import timezone

from apps.integrations.models import AuditLog
from apps.integrations.wb_client import WBApiError, WBClient
from apps.orders.models import Order
from apps.orders.services.assembly import get_seller_stage_counts
from apps.orders.services.wb_status import (
  WB_ACTIVE_DELIVERY_WB_STATUSES,
  WB_DELIVERED_WB_STATUSES,
  WB_SUPPLIER_DELIVERY,
  apply_wb_status_to_order,
)
from apps.sellers.models import Seller


def reconcile_wb_orders_for_seller(
  seller: Seller,
  status_map: dict[int, dict],
  *,
  user=None,
) -> dict:
  """Снять с «В доставке» завершённые и архивные заказы."""
  now = timezone.now()
  wb_ids_in_db = set(
    Order.objects.filter(seller=seller).values_list("wb_order_id", flat=True)
  )
  missing_ids = wb_ids_in_db - set(status_map.keys())

  shipped_delivered = Order.objects.filter(
    seller=seller,
    wb_status__in=WB_DELIVERED_WB_STATUSES,
  ).exclude(status=Order.Status.SHIPPED).update(status=Order.Status.SHIPPED, updated_at=now)

  shipped_inactive = Order.objects.filter(
    seller=seller,
    wb_supplier_status=WB_SUPPLIER_DELIVERY,
  ).exclude(
    wb_status__in=WB_ACTIVE_DELIVERY_WB_STATUSES,
  ).exclude(
    wb_status="",
  ).exclude(
    status=Order.Status.SHIPPED,
  ).update(status=Order.Status.SHIPPED, updated_at=now)

  shipped_missing = 0
  if missing_ids:
    shipped_missing = Order.objects.filter(
      seller=seller,
      wb_order_id__in=missing_ids,
      wb_supplier_status=WB_SUPPLIER_DELIVERY,
    ).exclude(status=Order.Status.SHIPPED).update(status=Order.Status.SHIPPED, updated_at=now)

  result = {
    "shipped_delivered": shipped_delivered,
    "shipped_inactive": shipped_inactive,
    "shipped_missing": shipped_missing,
    "missing_from_api": len(missing_ids),
  }

  if any(result[k] for k in ("shipped_delivered", "shipped_inactive", "shipped_missing")):
    AuditLog.objects.create(
      user=user,
      seller=seller,
      action_type=AuditLog.ActionType.WB_SYNC,
      message=(
        f"Сверка статусов WB: завершено {shipped_delivered + shipped_inactive + shipped_missing} заказов"
      ),
      details=result,
    )

  return result


def sync_order_statuses_for_seller(seller: Seller, client: WBClient, *, user=None) -> dict:
  """Запросить статусы WB для всех заказов селлера, обновить CRM и сверить счётчики."""
  wb_ids = list(
    Order.objects.filter(seller=seller).values_list("wb_order_id", flat=True)
  )
  if not wb_ids:
    counts = get_seller_stage_counts(seller)
    return {
      "statuses_fetched": 0,
      "statuses_updated": 0,
      "counts": counts,
    }

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

  updated = 0
  for order in Order.objects.filter(seller=seller):
    data = status_map.get(order.wb_order_id)
    if not data:
      continue
    if apply_wb_status_to_order(
      order,
      data.get("supplierStatus") or "",
      data.get("wbStatus") or "",
    ):
      updated += 1

  reconcile = reconcile_wb_orders_for_seller(seller, status_map, user=user)
  counts = get_seller_stage_counts(seller)

  return {
    "statuses_fetched": len(status_map),
    "statuses_updated": updated,
    "reconcile": reconcile,
    "counts": counts,
  }
