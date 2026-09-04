"""Очереди сборки FBS на вкладке «На сборке»: в работе, готовые, ошибки ЧЗ."""
from __future__ import annotations

from apps.orders.models import Order
from apps.orders.services.order_sticker import order_sticker_printed_in_crm
from apps.orders.services.wb_status import WB_SUPPLIER_ASSEMBLY
from apps.sellers.models import Seller
from apps.sellers.services.warehouse_filter import filter_orders_for_assembly
from apps.warehouse.services.marking_lookup import resolve_product_requires_marking


VERIFY_ERROR = "error"


def _assembly_confirm_orders_qs(seller: Seller):
  return filter_orders_for_assembly(
    Order.objects.filter(
      seller=seller,
      assembly_hidden=False,
      wb_supplier_status=WB_SUPPLIER_ASSEMBLY,
    ).select_related("product", "product__cell"),
    seller,
  )


def order_has_chz_error(order: Order) -> bool:
  if not resolve_product_requires_marking(order.product, order.barcode, order.seller):
    return False
  return (order.marking_verify_status or "").strip() == VERIFY_ERROR


def order_assembly_ready(order: Order) -> bool:
  """Баркод отсканирован, стикер привязан и напечатан в CRM (сборка завершена)."""
  if order_has_chz_error(order):
    return False
  return order_sticker_printed_in_crm(order)


def order_in_assembly(order: Order) -> bool:
  """Ещё ждёт скан баркода, ЧЗ и/или печать стикера."""
  if order_has_chz_error(order):
    return False
  if order_assembly_ready(order):
    return False
  if order.status in (Order.Status.CANCELLED, Order.Status.SHIPPED):
    return False
  return order.status in (Order.Status.IN_PICKING, Order.Status.ASSEMBLED)


def get_assembly_queue_status(seller: Seller) -> dict:
  """Счётчики и списки: «На сборке», «Готовые», «Ошибки ЧЗ»."""
  in_assembly: list[Order] = []
  ready: list[Order] = []
  errors: list[Order] = []

  for order in _assembly_confirm_orders_qs(seller):
    if order_has_chz_error(order):
      errors.append(order)
    elif order_assembly_ready(order):
      ready.append(order)
    elif order_in_assembly(order):
      in_assembly.append(order)

  return {
    "in_assembly_count": len(in_assembly),
    "ready_count": len(ready),
    "errors_count": len(errors),
    "in_assembly": in_assembly,
    "ready": ready,
    "errors": errors,
  }


def get_marking_queue_status(seller: Seller) -> dict:
  """Обратная совместимость для API marking-status."""
  data = get_assembly_queue_status(seller)
  return {
    **data,
    "unbound_count": data["in_assembly_count"],
    "unbound": data["in_assembly"],
  }
