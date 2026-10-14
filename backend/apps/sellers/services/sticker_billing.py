"""Обратная совместимость: биллинг перенесён на delivery_billing (факт «в доставку»)."""
from __future__ import annotations

from apps.orders.models import Order
from apps.sellers.models import Seller
from apps.sellers.services.delivery_billing import (
  load_weekly_shipped_orders,
  record_billing_on_order_delivery,
)


def record_billing_on_sticker_print(order: Order, *, seller: Seller) -> None:
  """Deprecated: начисления только при передаче в доставку."""
  if order.in_delivery_at is not None:
    record_billing_on_order_delivery(order, seller=seller)
