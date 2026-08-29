"""Очереди ЧЗ на вкладке «На сборке»: ошибки WB и заказы без привязки."""
from __future__ import annotations

from apps.orders.models import Order
from apps.orders.services.wb_status import WB_SUPPLIER_ASSEMBLY
from apps.sellers.models import Seller
from apps.sellers.services.warehouse_filter import filter_orders_for_assembly
from apps.warehouse.services.marking_lookup import resolve_product_requires_marking

VERIFY_ERROR = "error"


def _assembly_marking_orders_qs(seller: Seller):
  return filter_orders_for_assembly(
    Order.objects.filter(
      seller=seller,
      assembly_hidden=False,
      wb_supplier_status=WB_SUPPLIER_ASSEMBLY,
    ).select_related("product", "product__cell"),
    seller,
  )


def _requires_marking(order: Order) -> bool:
  return resolve_product_requires_marking(order.product, order.barcode, order.seller)


def get_marking_queue_status(seller: Seller) -> dict:
  """Счётчики и списки для панелей «Ошибки ЧЗ» и «Без ЧЗ»."""
  errors: list[Order] = []
  unbound: list[Order] = []

  for order in _assembly_marking_orders_qs(seller):
    if not _requires_marking(order):
      continue

    verify = (order.marking_verify_status or "").strip()
    if verify == VERIFY_ERROR:
      errors.append(order)
      continue

    if order.marking_code:
      continue

    if order.status in (Order.Status.IN_PICKING, Order.Status.ASSEMBLED):
      unbound.append(order)

  return {
    "errors_count": len(errors),
    "unbound_count": len(unbound),
    "errors": errors,
    "unbound": unbound,
  }
