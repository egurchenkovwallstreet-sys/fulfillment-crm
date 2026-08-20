"""Поштучная отправка заказов на сборку и в доставку через WB FBS API."""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.integrations.models import AuditLog
from apps.integrations.wb_client import WBApiError
from apps.orders.models import Order, Supply
from apps.orders.services.assembly import AssemblyError, _get_client, fetch_stickers_for_orders
from apps.orders.services.wb_status import (
  WB_DELIVERY_TAB_WB_STATUS,
  WB_SUPPLIER_ASSEMBLY,
  WB_SUPPLIER_DELIVERY,
  WB_SUPPLIER_NEW,
)
from apps.sellers.models import Seller
from apps.sellers.services.warehouse_filter import filter_orders_for_seller
from apps.warehouse.services.marking_lookup import resolve_product_requires_marking


class SupplyFlowError(Exception):
  def __init__(self, message: str, *, code: str = "error"):
    super().__init__(message)
    self.code = code


def _get_order(seller: Seller, order_id: int) -> Order:
  order = (
    filter_orders_for_seller(
      Order.objects.filter(pk=order_id, seller=seller).select_related("product"),
      seller,
    ).first()
  )
  if not order:
    raise SupplyFlowError("Заказ не найден", code="order_not_found")
  return order


def order_can_send_to_assembly(order: Order) -> bool:
  """WB new — можно отправить на сборку (CRM-статус не блокирует, кроме финальных)."""
  if order.status in (
    Order.Status.CANCELLED,
    Order.Status.SHIPPED,
    Order.Status.IN_DELIVERY,
  ):
    return False
  supplier = (order.wb_supplier_status or "").strip()
  return supplier in ("", WB_SUPPLIER_NEW)


def order_can_send_to_delivery(order: Order) -> bool:
  if (order.wb_supplier_status or "").strip() != WB_SUPPLIER_ASSEMBLY:
    return False
  if order.status not in (Order.Status.LABEL_PRINTED, Order.Status.MARKED):
    return False
  if resolve_product_requires_marking(order.product, order.barcode, order.seller):
    return order.marking_bound
  return True


def _parse_deliver_error(exc: WBApiError) -> str:
  text = str(exc).lower()
  if exc.status_code == 409:
    if "sgtin" in text or "marking" in text or "meta" in text:
      return (
        "WB отклонил передачу в доставку: не заполнена маркировка ЧЗ. "
        "Привяжите код и повторите."
      )
    return f"WB отклонил передачу в доставку: {exc}"
  return str(exc)


@transaction.atomic
def send_order_to_assembly(seller: Seller, order_id: int, *, user=None) -> dict:
  """
  Один заказ → поставка WB → статус confirm («На сборке»).
  Загружает стикер для печати.
  """
  order = _get_order(seller, order_id)

  if not order_can_send_to_assembly(order):
    raise SupplyFlowError(
      f"Заказ WB #{order.wb_order_id} нельзя отправить на сборку "
      f"(статус CRM: {order.get_status_display()}, WB: {order.wb_supplier_status or 'new'}).",
      code="invalid_status",
    )

  client = _get_client(seller)
  supply_name = f"CRM-{order.wb_order_id}-{timezone.now():%Y%m%d%H%M}"

  try:
    wb_supply_id = client.create_supply(supply_name)
    client.add_orders_to_supply(wb_supply_id, [order.wb_order_id])
  except WBApiError as exc:
    AuditLog.objects.create(
      user=user,
      seller=seller,
      action_type=AuditLog.ActionType.API_ERROR,
      message=f"Ошибка отправки на сборку WB #{order.wb_order_id}: {exc}",
      details={"order_id": order.id, "status_code": exc.status_code},
    )
    raise SupplyFlowError(str(exc), code="wb_assembly_failed") from exc

  stickers_fetched = 0
  sticker_error = ""
  try:
    stickers_fetched = fetch_stickers_for_orders(seller, [order], user=user)
    order.refresh_from_db()
  except AssemblyError as exc:
    sticker_error = str(exc)

  supply = Supply.objects.create(
    seller=seller,
    wb_supply_id=wb_supply_id,
    status=Supply.Status.FORMING,
  )
  supply.orders.add(order)

  order.status = Order.Status.IN_PICKING
  order.wb_supplier_status = WB_SUPPLIER_ASSEMBLY
  order.save(update_fields=["status", "wb_supplier_status", "updated_at"])

  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.ASSEMBLY,
    message=f"На сборку (WB): заказ #{order.wb_order_id}, поставка {wb_supply_id}",
    details={
      "order_id": order.id,
      "wb_supply_id": wb_supply_id,
      "stickers_fetched": stickers_fetched,
      "sticker_error": sticker_error,
    },
  )

  return {
    "order": order,
    "wb_supply_id": wb_supply_id,
    "stickers_fetched": stickers_fetched,
    "sticker_error": sticker_error,
  }


@transaction.atomic
def send_order_to_delivery(seller: Seller, order_id: int, *, user=None) -> dict:
  """
  Один заказ → deliver поставки WB → complete+waiting («В доставке»).
  """
  order = _get_order(seller, order_id)

  if not order_can_send_to_delivery(order):
    requires_marking = resolve_product_requires_marking(
      order.product, order.barcode, order.seller,
    )
    hint = ""
    if requires_marking and not order.marking_bound:
      hint = " Сначала привяжите Честный знак и распечатайте стикер."
    elif order.status not in (Order.Status.LABEL_PRINTED, Order.Status.MARKED):
      hint = " Сначала отсканируйте баркод и распечатайте стикер FBS."
    raise SupplyFlowError(
      f"Заказ WB #{order.wb_order_id} не готов к отправке в доставку.{hint}",
      code="not_ready",
    )

  supply = (
    Supply.objects.filter(
      seller=seller,
      orders=order,
      status=Supply.Status.FORMING,
    )
    .exclude(wb_supply_id="")
    .order_by("-created_at")
    .first()
  )
  if not supply:
    raise SupplyFlowError(
      f"Не найдена поставка WB для заказа #{order.wb_order_id}. "
      "Отправьте заказ на сборку заново.",
      code="no_supply",
    )

  client = _get_client(seller)
  try:
    client.deliver_supply(supply.wb_supply_id)
  except WBApiError as exc:
    AuditLog.objects.create(
      user=user,
      seller=seller,
      action_type=AuditLog.ActionType.API_ERROR,
      message=f"Ошибка доставки WB #{order.wb_order_id}: {exc}",
      details={
        "order_id": order.id,
        "wb_supply_id": supply.wb_supply_id,
        "status_code": exc.status_code,
      },
    )
    raise SupplyFlowError(_parse_deliver_error(exc), code="wb_deliver_failed") from exc

  supply_barcode_file = ""
  supply_barcode_value = ""
  try:
    barcode_payload = client.fetch_supply_barcode(supply.wb_supply_id)
    if isinstance(barcode_payload, dict):
      supply_barcode_file = barcode_payload.get("file") or ""
      supply_barcode_value = str(barcode_payload.get("barcode") or "")
  except WBApiError:
    pass

  order.status = Order.Status.IN_DELIVERY
  order.wb_supplier_status = WB_SUPPLIER_DELIVERY
  order.wb_status = WB_DELIVERY_TAB_WB_STATUS
  order.save(
    update_fields=["status", "wb_supplier_status", "wb_status", "updated_at"],
  )

  supply.status = Supply.Status.CONFIRMED
  supply.supply_barcode_printed = bool(supply_barcode_file)
  supply.save(update_fields=["status", "supply_barcode_printed", "updated_at"])

  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.SUPPLY,
    message=f"В доставку (WB): заказ #{order.wb_order_id}, поставка {supply.wb_supply_id}",
    details={
      "order_id": order.id,
      "wb_supply_id": supply.wb_supply_id,
      "supply_barcode": supply_barcode_value,
    },
  )

  return {
    "order": order,
    "wb_supply_id": supply.wb_supply_id,
    "supply_barcode_file": supply_barcode_file,
    "supply_barcode": supply_barcode_value,
  }


def count_orders_ready_for_assembly(seller: Seller) -> int:
  qs = filter_orders_for_seller(
    Order.objects.filter(seller=seller),
    seller,
  )
  return sum(1 for order in qs if order_can_send_to_assembly(order))


def send_orders_to_assembly_bulk(
  seller: Seller,
  *,
  order_ids: list[int] | None = None,
  user=None,
) -> dict:
  """Отправить на сборку все подходящие заказы (или выбранные) — по одному supply на заказ."""
  qs = filter_orders_for_seller(
    Order.objects.filter(seller=seller).select_related("product"),
    seller,
  )
  if order_ids is not None:
    qs = qs.filter(pk__in=order_ids)

  orders = [order for order in qs if order_can_send_to_assembly(order)]
  if not orders:
    raise SupplyFlowError(
      "Нет заказов для отправки на сборку. Обновите заказы из WB.",
      code="no_orders",
    )

  sent = 0
  stickers_total = 0
  errors: list[dict] = []

  for order in orders:
    try:
      result = send_order_to_assembly(seller, order.id, user=user)
      sent += 1
      stickers_total += result.get("stickers_fetched", 0)
    except SupplyFlowError as exc:
      errors.append({
        "order_id": order.id,
        "wb_order_id": order.wb_order_id,
        "error": str(exc),
      })

  if sent == 0 and errors:
    raise SupplyFlowError(
      f"Не удалось отправить ни одного заказа. Пример: {errors[0]['error']}",
      code="batch_failed",
    )

  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.ASSEMBLY,
    message=f"Массовая отправка на сборку: {sent} из {len(orders)}",
    details={"sent": sent, "total": len(orders), "errors": errors},
  )

  return {
    "sent": sent,
    "total": len(orders),
    "stickers_fetched": stickers_total,
    "errors": errors,
  }
