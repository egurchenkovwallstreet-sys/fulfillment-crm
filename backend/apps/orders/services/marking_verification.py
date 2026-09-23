"""Проверка статуса ЧЗ в WB после привязки (POST /api/marketplace/v3/orders/meta)."""
from __future__ import annotations

import logging

from django.core.cache import cache
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

logger = logging.getLogger(__name__)


def order_marking_ready(order: Order) -> bool:
  """ЧЗ привязан и проверен WB — можно передавать в доставку."""
  if not resolve_product_requires_marking(order.product, order.barcode, order.seller):
    return True

  status = (order.marking_verify_status or "").strip()
  if status == VERIFY_ERROR:
    return False
  if status != VERIFY_VERIFIED:
    return False
  return bool(order.marking_bound)


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


def _meta_marking_decision(meta_item: dict) -> str:
  """Худший статус маркировки из metaDetails и sgtin — как видит WB перед deliver."""
  decisions: list[str] = []
  details = meta_item.get("metaDetails") or meta_item.get("meta_details") or []
  if isinstance(details, dict):
    details = [details]
  for detail in details:
    if not isinstance(detail, dict):
      continue
    decision = str(
      detail.get("decision") or detail.get("status") or detail.get("checkStatus") or "",
    ).strip()
    if decision:
      decisions.append(decision)
  sgtin_decision = _extract_sgtin_decision(meta_item)
  if sgtin_decision:
    decisions.append(sgtin_decision)
  if not decisions:
    return ""
  rank = {VERIFY_ERROR: 3, VERIFY_PENDING: 2, VERIFY_VERIFIED: 1}
  best = decisions[0]
  best_rank = 0
  for decision in decisions:
    status, _ = parse_marking_verify_decision(decision)
    current = rank.get(status, 1)
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
  elif status == VERIFY_PENDING:
    order.marking_bound = False
    if order.status == Order.Status.MARKED:
      order.status = Order.Status.LABEL_PRINTED

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


def _orders_for_marking_verify(
  seller: Seller,
  order_ids: list[int] | None = None,
  *,
  force_recheck: bool = False,
):
  """Заказы на сборке, по которым уже есть ЧЗ или WB ещё не подтвердил код."""
  qs = Order.objects.filter(
    seller=seller,
    assembly_hidden=False,
    wb_supplier_status=WB_SUPPLIER_ASSEMBLY,
  )
  if order_ids:
    qs = qs.filter(pk__in=order_ids)
  elif force_recheck:
    qs = qs.filter(
      Q(marking_verify_status__in=[VERIFY_PENDING, VERIFY_VERIFIED, VERIFY_ERROR])
      | ~Q(marking_code=""),
    )
  else:
    # verified тоже перепроверяем — раньше CRM могла ошибочно поставить verified без meta WB
    qs = qs.exclude(marking_verify_status=VERIFY_ERROR).filter(
      Q(marking_verify_status__in=[VERIFY_PENDING, VERIFY_VERIFIED])
      | ~Q(marking_code=""),
    )
  result: list[Order] = []
  for order in qs.select_related("product", "seller"):
    if force_recheck or order_ids:
      result.append(order)
      continue
    has_code = bool((order.marking_code or "").strip())
    is_pending = (order.marking_verify_status or "").strip() == VERIFY_PENDING
    if has_code or is_pending:
      result.append(order)
  return result


def _resolve_marking_decision(
  meta_item: dict | None,
  *,
  has_code: bool,
  treat_missing_as_required: bool,
) -> str:
  """
  Статус ЧЗ только по ответу WB.
  Код в CRM без подтверждения в meta WB — pending, никогда не «filled».
  """
  if meta_item is None:
    if not has_code:
      return "required" if treat_missing_as_required else ""
    return VERIFY_PENDING

  decision = _meta_marking_decision(meta_item)
  if decision:
    return decision

  if has_code:
    return VERIFY_PENDING
  return "required" if treat_missing_as_required else ""


def sync_orders_marking_from_wb(
  seller: Seller,
  orders: list[Order],
  *,
  client=None,
  user=None,
  treat_missing_as_required: bool = False,
) -> tuple[list[dict], int]:
  """Обновить marking_verify_status в CRM по актуальным данным WB /orders/meta."""
  if not orders:
    return [], 0

  client = client or _get_client(seller)
  wb_ids = [int(order.wb_order_id) for order in orders if order.wb_order_id]
  if not wb_ids:
    return [], 0

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
      message=f"Ошибка синхронизации ЧЗ из WB: {exc}",
      details={"status_code": exc.status_code, "order_count": len(orders)},
    )
    raise AssemblyError(parse_wb_marking_error(exc), code="wb_verify_failed") from exc

  results: list[dict] = []
  for order in orders:
    meta_item = meta_by_wb_id.get(int(order.wb_order_id))
    has_code = bool((order.marking_code or "").strip())
    decision = _resolve_marking_decision(
      meta_item,
      has_code=has_code,
      treat_missing_as_required=treat_missing_as_required,
    )
    if not decision:
      continue
    previous_status = (order.marking_verify_status or "").strip()
    status = _apply_verify_result(order, decision)
    results.append({
      "order_id": order.id,
      "wb_order_id": order.wb_order_id,
      "status": status,
      "decision": decision,
      "error": order.marking_verify_error,
      "marking_bound": order.marking_bound,
      "changed": status != previous_status,
    })
    if status == VERIFY_ERROR and previous_status != VERIFY_ERROR:
      AuditLog.objects.create(
        user=user,
        seller=seller,
        action_type=AuditLog.ActionType.MARKING,
        message=f"ЧЗ отклонён WB для заказа #{order.wb_order_id}: {order.marking_verify_error}",
        details={"order_id": order.id, "decision": decision},
      )

  if results:
    from apps.orders.services.supply_flow import refresh_supply_readiness

    touched_ids = {item["order_id"] for item in results}
    for supply in Supply.objects.filter(
      seller=seller,
      status__in=(Supply.Status.FORMING, Supply.Status.READY),
      orders__id__in=touched_ids,
    ).distinct():
      refresh_supply_readiness(supply)

  return results, len(meta_by_wb_id)


def sync_supply_marking_from_wb(
  seller: Seller,
  supply: Supply,
  *,
  client=None,
  user=None,
) -> list[dict]:
  """Синхронизировать ЧЗ всех заказов поставки из WB перед deliver."""
  if not supply.wb_supply_id:
    return []
  client = client or _get_client(seller)
  try:
    wb_ids = client.fetch_supply_order_ids(supply.wb_supply_id)
  except WBApiError:
    return []
  if not wb_ids:
    return []
  orders = list(
    Order.objects.filter(
      seller=seller,
      wb_order_id__in=wb_ids,
      assembly_hidden=False,
    ).select_related("product", "seller"),
  )
  results, _meta_count = sync_orders_marking_from_wb(seller, orders, client=client, user=user)
  return results


REPUSH_CACHE_SEC = 300


def _maybe_repush_marking_to_wb(order: Order, *, user=None) -> bool:
  """Повторно отправить ЧЗ в WB, если код есть в CRM, а WB ещё не подтвердил."""
  code = (order.marking_code or "").strip()
  if not code:
    return False
  if (order.marking_verify_status or "").strip() != VERIFY_PENDING:
    return False
  cache_key = f"marking_repush:{order.id}"
  if cache.get(cache_key):
    return False
  from apps.orders.services.assembly import AssemblyError, _push_marking_code_to_wb

  try:
    _push_marking_code_to_wb(order, code, user=user)
  except AssemblyError:
    return False
  cache.set(cache_key, 1, REPUSH_CACHE_SEC)
  return True


def repair_assembly_marking_wb(seller: Seller, *, user=None, force: bool = False) -> dict:
  """
  Сверить ЧЗ готовых заказов с WB и дослать коды, которые не дошли (старый async-баг).
  """
  if not force:
    cache_key = f"marking_repair:{seller.id}"
    if cache.get(cache_key):
      return {"synced": 0, "repushed": 0, "downgraded": 0, "skipped": True}
    cache.set(cache_key, 1, 20)

  orders = list(_orders_for_marking_verify(seller, force_recheck=True))
  orders = [
    order
    for order in orders
    if (order.marking_code or "").strip()
    or (order.marking_verify_status or "").strip() in (VERIFY_PENDING, VERIFY_VERIFIED)
  ]
  if not orders:
    return {"synced": 0, "repushed": 0, "downgraded": 0}

  results, meta_count = sync_orders_marking_from_wb(
    seller,
    orders,
    user=user,
    treat_missing_as_required=True,
  )
  downgraded = sum(
    1
    for item in results
    if item.get("changed") and item["status"] == VERIFY_PENDING
  )

  repushed = 0
  for order in orders:
    order.refresh_from_db()
    if _maybe_repush_marking_to_wb(order, user=user):
      repushed += 1

  return {
    "synced": len(results),
    "repushed": repushed,
    "downgraded": downgraded,
    "meta_count": meta_count,
  }


def verify_marking_orders(
  seller: Seller,
  order_ids: list[int] | None = None,
  *,
  user=None,
  force_recheck: bool = False,
) -> list[dict]:
  """Опросить WB: принял ЧЗ → готовы к доставке, отклонил → ошибки ЧЗ."""
  orders = list(_orders_for_marking_verify(seller, order_ids, force_recheck=force_recheck))
  if not orders:
    return []

  results, meta_count = sync_orders_marking_from_wb(
    seller,
    orders,
    user=user,
    treat_missing_as_required=True,
  )
  if orders and meta_count == 0:
    wb_ids = [order.wb_order_id for order in orders]
    AuditLog.objects.create(
      user=user,
      seller=seller,
      action_type=AuditLog.ActionType.API_ERROR,
      message="WB не вернул статусы ЧЗ (пустой ответ /orders/meta)",
      details={
        "order_ids": [order.id for order in orders],
        "wb_ids": wb_ids[:20],
      },
    )
    raise AssemblyError(
      "WB не вернул статусы Честного знака. Нажмите «Проверить ЧЗ» ещё раз.",
      code="wb_verify_empty",
    )

  for item in results:
    if item["status"] == VERIFY_VERIFIED and item.get("changed"):
      AuditLog.objects.create(
        user=user,
        seller=seller,
        action_type=AuditLog.ActionType.MARKING,
        message=f"ЧЗ подтверждён WB для заказа #{item['wb_order_id']}",
        details={"order_id": item["order_id"], "decision": item["decision"]},
      )

  repushed = 0
  touched_ids = {item["order_id"] for item in results}
  for order in Order.objects.filter(pk__in=touched_ids):
    if _maybe_repush_marking_to_wb(order, user=user):
      repushed += 1
  if repushed:
    logger.info("Re-pushed %s marking codes to WB for seller=%s", repushed, seller.id)

  return results
