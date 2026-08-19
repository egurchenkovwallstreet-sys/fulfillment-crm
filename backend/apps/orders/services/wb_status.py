"""Сопоставление статусов Wildberries FBS и CRM."""

from django.db.models import Q

from apps.orders.models import Order

WB_SUPPLIER_NEW = "new"
WB_SUPPLIER_ASSEMBLY = "confirm"
WB_SUPPLIER_DELIVERY = "complete"

CANCEL_SUPPLIER_STATUSES = frozenset({"cancel", "cancel_carrier"})

CANCEL_WB_STATUSES = frozenset({
  "canceled",
  "canceled_by_client",
  "declined_by_client",
  "canceled_by_carrier",
  "cancel",
})

WB_DELIVERED_WB_STATUSES = frozenset({
  "sold",
  "ready_for_pickup",
  "defect",
})

WB_TERMINAL_WB_STATUSES = WB_DELIVERED_WB_STATUSES | CANCEL_WB_STATUSES

# Вкладка «В доставке» в ЛК WB = complete + sorted (отсортирован на складе WB)
WB_DELIVERY_TAB_WB_STATUS = "sorted"

WB_ACTIVE_SUPPLIER_STATUSES = frozenset({
  WB_SUPPLIER_NEW,
  WB_SUPPLIER_ASSEMBLY,
  WB_SUPPLIER_DELIVERY,
})

WB_SUPPLIER_LABELS = {
  WB_SUPPLIER_NEW: "Новый",
  WB_SUPPLIER_ASSEMBLY: "На сборке",
  WB_SUPPLIER_DELIVERY: "В доставке",
  "cancel": "Отменён",
  "cancel_carrier": "Отменён перевозчиком",
}

WB_STAGE_QUERIES = {
  "new": lambda: Q(wb_supplier_status=WB_SUPPLIER_NEW),
  "confirm": lambda: Q(wb_supplier_status=WB_SUPPLIER_ASSEMBLY),
  "in_picking": lambda: Q(wb_supplier_status=WB_SUPPLIER_ASSEMBLY),
  "complete": lambda: wb_in_delivery_q(),
  "in_delivery": lambda: wb_in_delivery_q(),
}


def wb_in_delivery_q() -> Q:
  """Как вкладка «В доставке» в ЛК WB: complete + wbStatus=sorted."""
  return (
    Q(wb_supplier_status=WB_SUPPLIER_DELIVERY)
    & Q(wb_status=WB_DELIVERY_TAB_WB_STATUS)
    & ~Q(status__in=[Order.Status.CANCELLED, Order.Status.SHIPPED])
  )


def wb_active_q() -> Q:
  return (
    Q(wb_supplier_status=WB_SUPPLIER_NEW)
    | Q(wb_supplier_status=WB_SUPPLIER_ASSEMBLY)
    | wb_in_delivery_q()
  )


def is_wb_cancelled(supplier_status: str, wb_status: str) -> bool:
  return supplier_status in CANCEL_SUPPLIER_STATUSES or wb_status in CANCEL_WB_STATUSES


def is_wb_in_delivery(supplier_status: str, wb_status: str) -> bool:
  """Только complete + sorted — как считает ЛК WB."""
  if supplier_status != WB_SUPPLIER_DELIVERY:
    return False
  if is_wb_cancelled(supplier_status, wb_status):
    return False
  if wb_status in WB_DELIVERED_WB_STATUSES:
    return False
  return wb_status == WB_DELIVERY_TAB_WB_STATUS


def apply_wb_status_to_order(order: Order, supplier_status: str, wb_status: str) -> bool:
  """Обновить WB-поля заказа и терминальные CRM-статусы."""
  supplier_status = (supplier_status or "").strip()
  wb_status = (wb_status or "").strip()

  changed_fields: set[str] = set()
  if order.wb_supplier_status != supplier_status:
    order.wb_supplier_status = supplier_status
    changed_fields.update({"wb_supplier_status"})
  if order.wb_status != wb_status:
    order.wb_status = wb_status
    changed_fields.add("wb_status")

  if is_wb_cancelled(supplier_status, wb_status):
    if order.status != Order.Status.CANCELLED:
      order.status = Order.Status.CANCELLED
      changed_fields.add("status")
  elif wb_status in WB_DELIVERED_WB_STATUSES:
    if order.status != Order.Status.SHIPPED:
      order.status = Order.Status.SHIPPED
      changed_fields.add("status")
  elif is_wb_in_delivery(supplier_status, wb_status):
    if order.status not in (Order.Status.CANCELLED, Order.Status.SHIPPED, Order.Status.IN_DELIVERY):
      order.status = Order.Status.IN_DELIVERY
      changed_fields.add("status")
  elif supplier_status == WB_SUPPLIER_DELIVERY:
    if order.status == Order.Status.IN_DELIVERY:
      order.status = Order.Status.SHIPPED
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


def compute_live_wb_counts(
  status_map: dict[int, dict],
  *,
  delivery_wb_ids: set[int] | None = None,
) -> dict[str, int]:
  counts = {"new": 0, "in_picking": 0, "in_delivery": 0, "cancelled": 0}
  for wb_id, item in status_map.items():
    supplier = (item.get("supplierStatus") or "").strip()
    wb = (item.get("wbStatus") or "").strip()
    if is_wb_cancelled(supplier, wb):
      counts["cancelled"] += 1
    elif supplier == WB_SUPPLIER_NEW:
      counts["new"] += 1
    elif supplier == WB_SUPPLIER_ASSEMBLY:
      counts["in_picking"] += 1
    elif is_wb_in_delivery(supplier, wb):
      if delivery_wb_ids is None or wb_id in delivery_wb_ids:
        counts["in_delivery"] += 1
  return counts


def save_wb_counts_to_seller(seller, counts: dict[str, int]) -> None:
  from django.utils import timezone

  seller.wb_count_new = counts.get("new", 0)
  seller.wb_count_assembly = counts.get("in_picking", 0)
  seller.wb_count_delivery = counts.get("in_delivery", 0)
  seller.wb_counts_synced_at = timezone.now()
  seller.save(
    update_fields=[
      "wb_count_new",
      "wb_count_assembly",
      "wb_count_delivery",
      "wb_counts_synced_at",
      "updated_at",
    ]
  )
