"""Очереди сборки FBS на вкладке «На сборке»: в работе, готовые, ошибки ЧЗ."""
from __future__ import annotations

from django.db import transaction

from apps.orders.models import Order
from apps.orders.services.order_sticker import order_sticker_printed_in_crm
from apps.orders.services.wb_status import WB_SUPPLIER_ASSEMBLY
from apps.sellers.models import Seller
from apps.sellers.services.warehouse_filter import filter_orders_for_assembly
from apps.warehouse.services.marking_lookup import resolve_product_requires_marking


VERIFY_ERROR = "error"
VERIFY_PENDING = "pending"


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


def order_chz_pending_verify(order: Order) -> bool:
  """ЧЗ отсканирован и ушёл в WB, ответ ещё не пришёл."""
  if not resolve_product_requires_marking(order.product, order.barcode, order.seller):
    return False
  if order_has_chz_error(order):
    return False
  return (order.marking_verify_status or "").strip() == VERIFY_PENDING


def order_assembly_ready(order: Order) -> bool:
  """Стикер напечатан — заказ в «Готовые» (WB может ещё проверять ЧЗ)."""
  if order_has_chz_error(order):
    return False
  return order_sticker_printed_in_crm(order)


def seller_has_unscanned_marking(seller: Seller) -> bool:
  """На сборке ещё есть заказы, где ЧЗ не отсканирован."""
  for order in _assembly_confirm_orders_qs(seller):
    if order_has_chz_error(order):
      continue
    if not resolve_product_requires_marking(order.product, order.barcode, order.seller):
      continue
    if (order.marking_code or "").strip():
      continue
    return True
  return False


def queue_last_pick_list_marking_verify(seller: Seller) -> bool:
  """Последний ЧЗ листа подбора: сразу поставить проверку WB (не ждать 10 мин)."""
  if seller_has_unscanned_marking(seller):
    return False
  has_pending = any(
    order_chz_pending_verify(order) for order in _assembly_confirm_orders_qs(seller)
  )
  if not has_pending:
    return False
  seller_id = seller.pk

  def _enqueue():
    from apps.integrations.tasks import verify_seller_marking_codes

    verify_seller_marking_codes.delay(seller_id)

  transaction.on_commit(_enqueue)
  return True


def order_in_assembly(order: Order) -> bool:
  """Ещё ждёт скан баркода, ЧЗ и/или печать стикера."""
  if order_has_chz_error(order):
    return False
  if order_assembly_ready(order):
    return False
  if order.status in (
    Order.Status.CANCELLED,
    Order.Status.SHIPPED,
    Order.Status.IN_DELIVERY,
  ):
    return False
  if (order.wb_supplier_status or "").strip() == WB_SUPPLIER_ASSEMBLY:
    return True
  return order.status in (
    Order.Status.IN_PICKING,
    Order.Status.ASSEMBLED,
    Order.Status.IN_SUPPLY,
  )


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
