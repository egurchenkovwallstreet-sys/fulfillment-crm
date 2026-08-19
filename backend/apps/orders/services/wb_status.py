"""Сопоставление статусов Wildberries FBS и CRM."""

from apps.orders.models import Order

WB_SUPPLIER_NEW = "new"
WB_SUPPLIER_ASSEMBLY = "confirm"
WB_SUPPLIER_DELIVERY = "complete"

CANCEL_SUPPLIER_STATUSES = frozenset({"cancel", "cancel_carrier"})
CANCEL_WB_STATUSES = frozenset({
  "canceled",
  "canceled_by_client",
  "declined_by_client",
  "cancel",
})

WB_ACTIVE_SUPPLIER_STATUSES = frozenset({
  WB_SUPPLIER_NEW,
  WB_SUPPLIER_ASSEMBLY,
  WB_SUPPLIER_DELIVERY,
})

WB_STAGE_FILTERS = {
  "new": {"wb_supplier_status": WB_SUPPLIER_NEW},
  "confirm": {"wb_supplier_status": WB_SUPPLIER_ASSEMBLY},
  "in_picking": {"wb_supplier_status": WB_SUPPLIER_ASSEMBLY},
  "complete": {"wb_supplier_status": WB_SUPPLIER_DELIVERY},
  "in_delivery": {"wb_supplier_status": WB_SUPPLIER_DELIVERY},
}

WB_SUPPLIER_LABELS = {
  WB_SUPPLIER_NEW: "Новый",
  WB_SUPPLIER_ASSEMBLY: "На сборке",
  WB_SUPPLIER_DELIVERY: "В доставке",
  "cancel": "Отменён",
  "cancel_carrier": "Отменён перевозчиком",
}


def is_wb_cancelled(supplier_status: str, wb_status: str) -> bool:
  return supplier_status in CANCEL_SUPPLIER_STATUSES or wb_status in CANCEL_WB_STATUSES


def apply_wb_status_to_order(order: Order, supplier_status: str, wb_status: str) -> bool:
  """Обновить WB-поля заказа и терминальные CRM-статусы. Возвращает True, если были изменения."""
  supplier_status = (supplier_status or "").strip()
  wb_status = (wb_status or "").strip()

  changed_fields: set[str] = set()
  if order.wb_supplier_status != supplier_status:
    order.wb_supplier_status = supplier_status
    changed_fields.update({"wb_supplier_status"})
  if order.wb_status != wb_status:
    order.wb_status = wb_status
    changed_fields.update({"wb_status"})

  if is_wb_cancelled(supplier_status, wb_status):
    if order.status != Order.Status.CANCELLED:
      order.status = Order.Status.CANCELLED
      changed_fields.add("status")
  elif supplier_status == WB_SUPPLIER_DELIVERY:
    if order.status not in (Order.Status.CANCELLED, Order.Status.SHIPPED, Order.Status.IN_DELIVERY):
      order.status = Order.Status.IN_DELIVERY
      changed_fields.add("status")
  elif supplier_status == WB_SUPPLIER_ASSEMBLY:
    if order.status == Order.Status.NEW:
      order.status = Order.Status.IN_SUPPLY
      changed_fields.add("status")

  if changed_fields:
    changed_fields.add("updated_at")
    order.save(update_fields=sorted(changed_fields))
    return True
  return False
