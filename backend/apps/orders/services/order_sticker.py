"""Проверка, что стикер FBS распечатан через CRM (без тяжёлых зависимостей)."""
from __future__ import annotations

from apps.orders.models import Order


def order_sticker_printed_in_crm(order: Order) -> bool:
  """Стикер реально прошёл сборку в CRM (скан → печать), а не только загружен из WB."""
  part_a = (order.sticker_part_a or "").strip()
  part_b = (order.sticker_part_b or "").strip()
  if not (part_a and part_b):
    return False
  return order.status in (Order.Status.LABEL_PRINTED, Order.Status.MARKED)
