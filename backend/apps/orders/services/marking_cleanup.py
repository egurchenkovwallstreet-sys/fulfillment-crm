"""Удаление кодов ЧЗ из БД через 3 часа после передачи в доставку."""
from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from apps.orders.models import Order, OzonPosting

MARKING_RETENTION_HOURS = 3


def stamp_in_delivery_at(order: Order, *, at=None) -> None:
  """Зафиксировать момент «в доставке» для отложенного удаления ЧЗ."""
  if order.in_delivery_at is not None:
    return
  order.in_delivery_at = at or timezone.now()
  order.save(update_fields=["in_delivery_at", "updated_at"])


def _clear_order_marking(order: Order) -> bool:
  if not (order.marking_code or "").strip():
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
  has_code = bool((posting.marking_code or "").strip()) or bool(posting.marking_codes)
  if not has_code:
    return False
  posting.marking_code = ""
  posting.marking_codes = []
  posting.marking_bound = False
  posting.save(update_fields=["marking_code", "marking_codes", "marking_bound", "updated_at"])
  return True


def clear_expired_marking_codes(*, hours: int = MARKING_RETENTION_HOURS) -> dict:
  """Стереть ЧЗ, если с момента передачи в доставку прошло hours часов."""
  cutoff = timezone.now() - timedelta(hours=hours)

  wb_cleared = 0
  wb_orders = Order.objects.filter(
    in_delivery_at__isnull=False,
    in_delivery_at__lte=cutoff,
  ).exclude(marking_code="")
  for order in wb_orders.iterator():
    if _clear_order_marking(order):
      wb_cleared += 1

  ozon_cleared = 0
  ozon_postings = OzonPosting.objects.filter(
    shipped_at__isnull=False,
    shipped_at__lte=cutoff,
  )
  for posting in ozon_postings.iterator():
    if _clear_posting_marking(posting):
      ozon_cleared += 1

  return {
    "wb_cleared": wb_cleared,
    "ozon_cleared": ozon_cleared,
    "cutoff": cutoff.isoformat(),
    "retention_hours": hours,
  }
