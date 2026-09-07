"""Удаление кодов ЧЗ из БД — ежедневно в 23:59 для отгруженных заказов."""
from __future__ import annotations

from django.db.models import Q

from apps.orders.models import Order, OzonPosting


def stamp_in_delivery_at(order: Order, *, at=None) -> None:
  """Зафиксировать момент «в доставке» (для учёта, не для срока хранения ЧЗ)."""
  from django.utils import timezone

  if order.in_delivery_at is not None:
    return
  order.in_delivery_at = at or timezone.now()
  order.save(update_fields=["in_delivery_at", "updated_at"])


def _order_has_marking_data(order: Order) -> bool:
  return bool(
    (order.marking_code or "").strip()
    or order.marking_bound
    or (order.marking_verify_status or "").strip()
    or (order.marking_verify_error or "").strip()
  )


def _clear_order_marking(order: Order) -> bool:
  if not _order_has_marking_data(order):
    return False
  order.marking_code = ""
  order.marking_bound = False
  order.marking_verify_status = ""
  order.marking_verify_error = ""
  order.save(
    update_fields=[
      "marking_code",
      "marking_bound",
      "marking_verify_status",
      "marking_verify_error",
      "updated_at",
    ],
  )
  return True


def _clear_posting_marking(posting: OzonPosting) -> bool:
  has_code = (
    bool((posting.marking_code or "").strip())
    or bool(posting.marking_codes)
    or posting.marking_bound
  )
  if not has_code:
    return False
  posting.marking_code = ""
  posting.marking_codes = []
  posting.marking_bound = False
  posting.save(update_fields=["marking_code", "marking_codes", "marking_bound", "updated_at"])
  return True


def _shipped_wb_orders_with_marking():
  return Order.objects.exclude(marking_code="").filter(
    Q(status__in=[Order.Status.IN_DELIVERY, Order.Status.SHIPPED])
    | Q(in_delivery_at__isnull=False),
  )


def _shipped_ozon_postings_with_marking():
  return OzonPosting.objects.filter(
    Q(crm_stage=OzonPosting.CrmStage.IN_DELIVERY)
    | Q(shipped_at__isnull=False),
  )


def clear_daily_shipped_marking_codes() -> dict:
  """
  Ежедневная очистка (23:59): CRM забывает ЧЗ отгруженных заказов.
  На следующий день тот же физический код можно сканировать как новый.
  """
  wb_cleared = 0
  for order in _shipped_wb_orders_with_marking().iterator():
    if _clear_order_marking(order):
      wb_cleared += 1

  ozon_cleared = 0
  for posting in _shipped_ozon_postings_with_marking().iterator():
    if _clear_posting_marking(posting):
      ozon_cleared += 1

  return {
    "wb_cleared": wb_cleared,
    "ozon_cleared": ozon_cleared,
    "mode": "daily_shipped",
  }


def clear_expired_marking_codes(*, hours: int | None = None) -> dict:
  """Обратная совместимость для старых вызовов — делегирует в ежедневную очистку."""
  del hours
  return clear_daily_shipped_marking_codes()


def clear_all_delivered_marking_codes() -> dict:
  """Срочный сброс: удалить все ЧЗ у заказов, уже переданных в доставку."""
  return clear_daily_shipped_marking_codes()
