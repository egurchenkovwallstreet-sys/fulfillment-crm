"""Проверка статуса ЧЗ в WB после привязки (POST /api/marketplace/v3/orders/meta)."""
from __future__ import annotations

from django.db.models import Q

from apps.integrations.models import AuditLog
from apps.integrations.wb_client import WBApiError
from apps.orders.models import Order, Supply
from apps.orders.services.assembly import AssemblyError, _get_client
from apps.orders.services.marking import parse_marking_verify_decision, parse_wb_marking_error
from apps.orders.services.wb_status import WB_SUPPLIER_ASSEMBLY
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
  return order.marking_bound


def _sgtin_key(value: str) -> bool:
  key = (value or "").strip().lower()
  return key in ("sgtin", "kiz", "cis") or "sgtin" in key


def _detail_has_value(detail: dict) -> bool:
  for field in ("value", "values", "sgtin", "sgtins"):
    raw = detail.get(field)
    if isinstance(raw, list):
      if any(str(item or "").strip() for item in raw):
        return True
    elif str(raw or "").strip():
      return True
  return False


def _decision_from_sgtin_blob(blob) -> list[str]:
  found: list[str] = []
  if isinstance(blob, dict):
    decision = str(
      blob.get("decision") or blob.get("status") or blob.get("checkStatus") or "",
    ).strip()
    if decision:
      found.append(decision)
    elif _detail_has_value(blob):
      found.append("filled")
  elif isinstance(blob, list):
    for item in blob:
      found.extend(_decision_from_sgtin_blob(item))
  elif str(blob or "").strip():
    found.append("filled")
  return found


def _collect_sgtin_decisions(meta_item: dict) -> list[str]:
  found: list[str] = []
  details = meta_item.get("metaDetails") or meta_item.get("meta_details") or []
  if isinstance(details, dict):
    details = [details]
  for detail in details:
    if not isinstance(detail, dict):
      continue
    if not _sgtin_key(str(detail.get("key") or detail.get("name") or detail.get("type") or "")):
      continue
    decision = str(
      detail.get("decision") or detail.get("status") or detail.get("checkStatus") or "",
    ).strip()
    extra = str(
      detail.get("error") or detail.get("failReason") or detail.get("comment") or "",
    ).strip()
    if decision:
      found.append(decision)
    elif extra:
      found.append("invalid")
    elif _detail_has_value(detail):
      found.append("filled")

  meta = meta_item.get("meta") or {}
  if isinstance(meta, dict):
    found.extend(_decision_from_sgtin_blob(meta.get("sgtin")))
  found.extend(_decision_from_sgtin_blob(meta_item.get("sgtin")))
  return found


def _extract_sgtin_decision(meta_item: dict) -> str:
  """Отказ WB важнее pending; filled / код без статуса — принят к доставке."""
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


def _meta_order_id(item: dict) -> int | None:
  for key in ("id", "orderId", "order_id", "orderID", "rid"):
    value = item.get(key)
    if value is None or str(value).strip() == "":
      continue
    try:
      return int(value)
    except (TypeError, ValueError):
      continue
  return None


def _orders_for_marking_verify(seller: Seller, order_ids: list[int] | None = None):
  """Заказы на сборке, по которым уже есть ЧЗ или WB ещё не подтвердил код."""
  qs = (
    Order.objects.filter(
      seller=seller,
      assembly_hidden=False,
      wb_supplier_status=WB_SUPPLIER_ASSEMBLY,
    )
    .exclude(marking_verify_status=VERIFY_VERIFIED)
    .exclude(marking_verify_status=VERIFY_ERROR)
    .filter(Q(marking_verify_status=VERIFY_PENDING) | ~Q(marking_code=""))
  )
  if order_ids:
    qs = qs.filter(pk__in=order_ids)
  result: list[Order] = []
  for order in qs.select_related("product", "seller"):
    has_code = bool((order.marking_code or "").strip())
    is_pending = (order.marking_verify_status or "").strip() == VERIFY_PENDING
    if has_code or is_pending:
      result.append(order)
  return result


def verify_marking_orders(
  seller: Seller,
  order_ids: list[int] | None = None,
  *,
  user=None,
) -> list[dict]:
  """Опросить WB: принял ЧЗ → готовы к доставке, отклонил → ошибки ЧЗ."""
  orders = list(_orders_for_marking_verify(seller, order_ids))
  if not orders:
    return []

  client = _get_client(seller)
  wb_ids = [order.wb_order_id for order in orders]
  meta_by_wb_id: dict[int, dict] = {}
  try:
    for offset in range(0, len(wb_ids), 100):
      for item in client.fetch_orders_meta(wb_ids[offset:offset + 100]):
        wb_id = _meta_order_id(item)
        if wb_id is not None:
          meta_by_wb_id[wb_id] = item
  except WBApiError as exc:
    AuditLog.objects.create(
      user=user,
      seller=seller,
      action_type=AuditLog.ActionType.API_ERROR,
      message=f"Ошибка проверки ЧЗ WB: {exc}",
      details={"status_code": exc.status_code, "order_ids": order_ids},
    )
    raise AssemblyError(parse_wb_marking_error(exc), code="wb_verify_failed") from exc

  if not meta_by_wb_id or not any(int(order.wb_order_id) in meta_by_wb_id for order in orders):
    AuditLog.objects.create(
      user=user,
      seller=seller,
      action_type=AuditLog.ActionType.API_ERROR,
      message="WB не вернул статусы ЧЗ (пустой ответ /orders/meta)",
      details={
        "order_ids": [order.id for order in orders],
        "wb_ids": wb_ids[:20],
        "meta_ids": list(meta_by_wb_id.keys())[:20],
      },
    )
    raise AssemblyError(
      "WB не вернул статусы Честного знака. Нажмите «Проверить ЧЗ» ещё раз.",
      code="wb_verify_empty",
    )

  results: list[dict] = []
  for order in orders:
    meta_item = meta_by_wb_id.get(int(order.wb_order_id))
    has_code = bool((order.marking_code or "").strip())
    if meta_item is None:
      decision = "filled" if has_code else "required"
    else:
      decision = _extract_sgtin_decision(meta_item) or ("filled" if has_code else "required")
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

  from apps.orders.services.supply_flow import refresh_supply_readiness

  touched_ids = {order.id for order in orders}
  for supply in Supply.objects.filter(
    seller=seller,
    status__in=(Supply.Status.FORMING, Supply.Status.READY),
    orders__id__in=touched_ids,
  ).distinct():
    refresh_supply_readiness(supply)

  return results
