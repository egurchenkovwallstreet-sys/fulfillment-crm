"""Проверка, что стикер FBS распечатан через CRM (без тяжёлых зависимостей)."""
from __future__ import annotations

from apps.orders.models import Order


def order_sticker_printed_in_crm(order: Order) -> bool:
  part_a = (order.sticker_part_a or "").strip()
  part_b = (order.sticker_part_b or "").strip()
  if part_a and part_b and order.has_sticker:
    return True
  return order.status in (Order.Status.LABEL_PRINTED, Order.Status.MARKED) and bool(
    part_a and part_b
  )
