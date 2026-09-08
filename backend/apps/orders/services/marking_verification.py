"""Проверка статуса ЧЗ в WB после привязки (POST /api/marketplace/v3/orders/meta)."""
from __future__ import annotations

from apps.integrations.models import AuditLog
from apps.integrations.wb_client import WBApiError
from apps.orders.models import Order
from apps.orders.services.assembly import AssemblyError, _get_client
from apps.orders.services.marking import parse_marking_verify_decision, parse_wb_marking_error
from apps.sellers.models import Seller
from apps.warehouse.services.marking_lookup import resolve_product_requires_marking

VERIFY_PENDING = "pending"
VERIFY_VERIFIED = "verified"
VERIFY_ERROR = "error"


def order_marking_ready(order: Order) -> bool:
  """ЧЗ привязан и проверен WB — можно передавать в доставку."""
  if not resolve_product_requires_marking(order.product, order.barcode, order.seller):
    return True
  status = (order.marking_verify_status or "").strip()
  if status == VERIFY_ERROR:
    return False
  if status == VERIFY_PENDING:
    return False
  if status == VERIFY_VERIFIED:
    return order.marking_bound
  # Заказы до внедрения проверки: только marking_bound
  return order.marking_bound


def _collect_sgtin_decisions(meta_item: dict) -> list[str]:
  found: list[str] = []
  for detail in meta_item.get("metaDetails") or []:
    if (detail.get("key") or "").lower() != "sgtin":
      continue
    decision = str(detail.get("decision") or detail.get("status") or "").strip()
    extra = str(
      detail.get("error") or detail.get("failReason") or detail.get("comment") or "",
    ).strip()
    if decision:
      found.append(decision)
    elif extra:
      found.append("invalid")
    elif detail.get("value"):
      found.append(VERIFY_PENDING)

  meta = meta_item.get("meta") or {}
  sgtin = meta.get("sgtin")
  if isinstance(sgtin, dict):
    decision = str(sgtin.get("decision") or sgtin.get("status") or "").strip()
    if decision:
      found.append(decision)
    elif sgtin.get("value"):
      found.append(VERIFY_PENDING)
  elif isinstance(sgtin, str) and sgtin.strip():
    found.append(VERIFY_PENDING)
  return found


def _extract_sgtin_decision(meta_item: dict) -> str:
  """Статус sgtin из metaDetails: если WB отклонил хотя бы один код — это ошибка ЧЗ."""
  decisions = _collect_sgtin_decisions(meta_item)
  if not decisions:
    return ""
  rank = {"error": 3, "pending": 2, "verified": 1}
  best = decisions[0]
  best_rank = 0
  for decision in decisions:
    status, _ = parse_marking_verify_decision(decision)
    current = rank.get(status, 3)
    if current > best_rank:
      best_rank = current
      best = decision
  return best


def _apply_verify_result(order: Order, decision: str) -> str:
  status, error = parse_marking_verify_decision(decision)
  order.marking_verify_status = status
  order.marking_verify_error = error or ""

  if status == VERIFY_VERIFIED:
    order.marking_bound = True
    order.status = Order.Status.MARKED
  elif status == VERIFY_ERROR:
    order.marking_bound = False

  order.save(
    update_fields=[
      "marking_verify_status",
      "marking_verify_error",
      "marking_bound",
      "status",
      "updated_at",
    ]
  )
  return status


def _orders_for_marking_verify(seller: Seller, order_ids: list[int] | None = None):
  """Заказы с ЧЗ, у которых WB ещё не подтвердил код (pending / пустой статус)."""
  qs = (
    Order.objects.filter(seller=seller)
    .exclude(marking_code="")
    .exclude(marking_verify_status=VERIFY_VERIFIED)
    .exclude(marking_verify_status=VERIFY_ERROR)
  )
  if order_ids:
    qs = qs.filter(pk__in=order_ids)
  return qs.select_related("product", "seller")


def verify_marking_orders(
  seller: Seller,
  order_ids: list[int] | None = None,
  *,
  user=None,
) -> list[dict]:
  """Опросить WB и обновить статусы проверки ЧЗ для заказов селлера."""
  orders = [
    order
    for order in _orders_for_marking_verify(seller, order_ids)
    if resolve_product_requires_marking(order.product, order.barcode, order.seller)
  ]
  if not orders:
    return []

  client = _get_client(seller)
  wb_ids = [order.wb_order_id for order in orders]
  meta_by_wb_id: dict[int, dict] = {}
  try:
    for offset in range(0, len(wb_ids), 100):
      for item in client.fetch_orders_meta(wb_ids[offset:offset + 100]):
        wb_id = item.get("id")
        if wb_id is not None:
          meta_by_wb_id[int(wb_id)] = item
  except WBApiError as exc:
    AuditLog.objects.create(
      user=user,
      seller=seller,
      action_type=AuditLog.ActionType.API_ERROR,
      message=f"Ошибка проверки ЧЗ WB: {exc}",
      details={"status_code": exc.status_code, "order_ids": order_ids},
    )
    raise AssemblyError(parse_wb_marking_error(exc), code="wb_verify_failed") from exc

  results: list[dict] = []
  for order in orders:
    meta_item = meta_by_wb_id.get(order.wb_order_id, {})
    decision = _extract_sgtin_decision(meta_item)
    # WB не видит sgtin в meta — для CRM код «не принят», а не «всё ещё проверяется».
    if not decision and order.marking_code:
      decision = "required"
    status = _apply_verify_result(order, decision)
    results.append({
      "order_id": order.id,
      "wb_order_id": order.wb_order_id,
      "status": status,
      "decision": decision,
      "error": order.marking_verify_error,
      "marking_bound": order.marking_bound,
    })
    if status == VERIFY_VERIFIED:
      AuditLog.objects.create(
        user=user,
        seller=seller,
        action_type=AuditLog.ActionType.MARKING,
        message=f"ЧЗ подтверждён WB для заказа #{order.wb_order_id}",
        details={"order_id": order.id, "decision": decision},
      )
    elif status == VERIFY_ERROR:
      AuditLog.objects.create(
        user=user,
        seller=seller,
        action_type=AuditLog.ActionType.MARKING,
        message=f"ЧЗ отклонён WB для заказа #{order.wb_order_id}: {order.marking_verify_error}",
        details={"order_id": order.id, "decision": decision},
      )

  return results
