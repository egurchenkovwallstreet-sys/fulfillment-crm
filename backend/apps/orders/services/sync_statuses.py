from apps.integrations.models import AuditLog
from apps.integrations.wb_client import WBApiError, WBClient
from apps.orders.models import Order
from apps.orders.services.wb_status import apply_wb_status_to_order
from apps.sellers.models import Seller


def sync_order_statuses_for_seller(seller: Seller, client: WBClient, *, user=None) -> dict:
  """Запросить статусы WB для всех заказов селлера и обновить CRM."""
  wb_ids = list(
    Order.objects.filter(seller=seller).values_list("wb_order_id", flat=True)
  )
  if not wb_ids:
    return {"statuses_fetched": 0, "statuses_updated": 0}

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

  return {
    "statuses_fetched": len(status_map),
    "statuses_updated": updated,
  }
