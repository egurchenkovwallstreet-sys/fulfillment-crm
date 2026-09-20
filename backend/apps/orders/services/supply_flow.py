"""Поштучная отправка заказов на сборку и в доставку через WB FBS API."""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import date
from zoneinfo import ZoneInfo

from django.core.cache import cache
from django.db import transaction
from django.db.models import Exists, OuterRef, Q, QuerySet
from django.utils import timezone

from apps.integrations.models import AuditLog
from apps.integrations.wb_client import (
  SUPPLY_CREATE_SETTLE_SEC,
  WBApiError,
)
from apps.orders.models import Order, PickList, Supply
from apps.orders.services.assembly import AssemblyError, _get_client, fetch_stickers_for_orders
from apps.orders.services.assembly_queue import order_in_assembly, queue_last_pick_list_marking_verify
from apps.orders.services.wb_status import (
  CANCEL_SUPPLIER_STATUSES,
  CANCEL_WB_STATUSES,
  WB_STAGE_QUERIES,
  WB_STATUS_AFTER_DELIVER,
  is_terminal_cancelled_order,
  order_departed_wb_assembly,
  WB_SUPPLIER_ASSEMBLY,
  WB_SUPPLIER_DELIVERY,
  WB_SUPPLIER_NEW,
  wb_in_delivery_q,
)
from apps.sellers.models import Seller
from apps.sellers.services.warehouse_filter import (
  filter_orders_for_assembly,
  filter_supplies_for_assembly,
  get_enabled_wb_warehouse_ids,
  seller_has_warehouse_config,
)
from apps.orders.services.marking_verification import (
  VERIFY_ERROR,
  VERIFY_PENDING,
  order_marking_ready,
  sync_supply_marking_from_wb,
  verify_marking_orders,
)
from apps.orders.services import shipping_points_catalog as _shipping_catalog
from apps.warehouse.services.marking_lookup import resolve_product_requires_marking
from apps.warehouse.services.stock_deduction import (
  StockDeductionError,
  assert_order_stock_deducted_at_print,
  order_sticker_printed_in_crm,
  stock_deduction_info,
)

logger = logging.getLogger(__name__)


def _schedule_billing_refresh_after_delivery(seller: Seller) -> None:
  try:
    from apps.sellers.services.admin_billing_cache import (
      schedule_admin_billing_refresh_after_delivery,
    )

    schedule_admin_billing_refresh_after_delivery(fulfillment_id=seller.fulfillment_id)
  except Exception:
    logger.exception("billing refresh schedule failed seller=%s", seller.id)


class SupplyFlowError(Exception):
  def __init__(self, message: str, *, code: str = "error"):
    super().__init__(message)
    self.code = code


def _get_order(seller: Seller, order_id: int) -> Order:
  order = (
    filter_orders_for_assembly(
      Order.objects.filter(pk=order_id, seller=seller)
      .select_related("product", "pick_list"),
      seller,
    ).first()
  )
  if not order:
    raise SupplyFlowError("Заказ не найден", code="order_not_found")
  return order


def order_can_send_to_assembly(order: Order) -> bool:
  """WB new — можно отправить на сборку (CRM-статус не блокирует, кроме финальных)."""
  if order.status in (
    Order.Status.CANCELLED,
    Order.Status.SHIPPED,
    Order.Status.IN_DELIVERY,
  ):
    return False
  supplier = (order.wb_supplier_status or "").strip()
  return supplier in ("", WB_SUPPLIER_NEW)


def new_orders_ready_for_transfer_queryset(seller: Seller) -> QuerySet:
  """Новые заказы в CRM, готовые к передаче на сборку без доп. запросов к WB."""
  return (
    new_stage_orders_queryset(seller)
    .filter(wb_warehouse_id__isnull=False)
    .exclude(barcode="")
    .exclude(barcode__isnull=True)
  )


def get_assembly_transfer_readiness(seller: Seller) -> dict[str, int]:
  """Сколько новых заказов уже в CRM и готовы к кнопке «Передать на сборку»."""
  from apps.orders.services.wb_status import get_wb_lk_tab_counts

  tab_counts = get_wb_lk_tab_counts(seller)
  wb_new_total = int(tab_counts.get("new") or 0)
  ready = 0
  for order in new_orders_ready_for_transfer_queryset(seller).only(
    "id",
    "status",
    "wb_supplier_status",
  ):
    if order_can_send_to_assembly(order):
      ready += 1
  pending = max(0, wb_new_total - ready)
  return {
    "assembly_ready": ready,
    "assembly_pending": pending,
    "wb_new_total": wb_new_total,
  }


def order_can_send_to_delivery(order: Order) -> bool:
  if (order.marking_verify_status or "").strip() == VERIFY_ERROR:
    return False
  if (order.wb_supplier_status or "").strip() != WB_SUPPLIER_ASSEMBLY:
    return False
  if not order_sticker_printed_in_crm(order):
    return False
  if order.status not in (Order.Status.LABEL_PRINTED, Order.Status.MARKED):
    return False
  if resolve_product_requires_marking(order.product, order.barcode, order.seller):
    return order_marking_ready(order)
  return True


MOSCOW_TZ = ZoneInfo("Europe/Moscow")


def _unwrap_wb_supply_dict(payload: dict) -> dict:
  if not payload:
    return {}
  for key in ("supply", "data", "result"):
    nested = payload.get(key)
    if isinstance(nested, dict) and (
      nested.get("id") or nested.get("scanDt") or nested.get("scan_dt")
      or nested.get("shippingPointId") is not None
    ):
      return nested
  return payload


def _wb_error_tokens(exc: WBApiError) -> str:
  payload = getattr(exc, "payload", {}) or {}
  chunks = [str(exc), str(getattr(exc, "code", "") or "")]
  if isinstance(payload, dict):
    chunks.append(str(payload.get("code") or ""))
    chunks.append(str(payload.get("message") or ""))
    chunks.append(str(payload.get("detail") or ""))
    data = payload.get("data")
    if isinstance(data, dict):
      chunks.append(str(data))
  return " ".join(chunks).lower()


def _format_meta_validation_orders(payload: dict) -> str:
  data = payload.get("data")
  if not isinstance(data, dict):
    return ""
  orders = data.get("orders")
  if not isinstance(orders, list) or not orders:
    return ""
  lines: list[str] = []
  for item in orders[:5]:
    if not isinstance(item, dict):
      continue
    wb_id = item.get("id") or item.get("orderId") or item.get("order_id")
    details = item.get("metaDetails") or item.get("meta_details") or []
    if not isinstance(details, list):
      details = [details]
    detail_bits: list[str] = []
    for detail in details:
      if not isinstance(detail, dict):
        continue
      key = str(detail.get("key") or detail.get("name") or "meta").strip()
      decision = str(detail.get("decision") or detail.get("status") or "").strip()
      if key or decision:
        detail_bits.append(f"{key}={decision or '?'}")
    suffix = f" ({', '.join(detail_bits)})" if detail_bits else ""
    lines.append(f"#{wb_id}{suffix}")
  if not lines:
    return ""
  extra = f" и ещё {len(orders) - len(lines)}" if len(orders) > len(lines) else ""
  return " Проблемные заказы WB: " + ", ".join(lines) + extra + "."


def _parse_shipping_method_error(exc: WBApiError) -> str:
  text = _wb_error_tokens(exc)
  code = str(getattr(exc, "code", "") or "")
  if any(token in text for token in ("invalidshippingdt", "invalid_shipping_dt")):
    return (
      "WB отклонил дату отгрузки — выберите сегодня или более позднюю дату "
      "в окне «В доставку» и повторите."
    )
  if any(token in text for token in ("supplyalreadyscanned", "already scanned")):
    return (
      "WB уже отсканировал эту поставку на пункте приёмки. "
      "Нажмите «Обновить заказы» — CRM подтянет статус из WB."
    )
  if any(token in text for token in ("unsuitableshippingtype", "waybill")):
    return (
      "WB отклонил способ отгрузки. Для CRM используйте доставку силами продавца "
      "(selfShipping), без транспортной компании."
    )
  if any(token in text for token in ("notfound", "incorrectparameter", "incorrect request")):
    return (
      f"WB не принял пункт отгрузки или параметры пропуска. "
      f"Выберите другой пункт из списка (#ID в строке) и повторите. Ответ WB: {exc}"
    )
  if code and code not in ("unknown", ""):
    return f"WB не принял параметры отгрузки ({code}): {exc}"
  return f"Не удалось установить параметры отгрузки WB: {exc}"


def _parse_deliver_error(exc: WBApiError) -> str:
  text = _wb_error_tokens(exc)
  payload = getattr(exc, "payload", {}) or {}
  code = str(getattr(exc, "code", "") or payload.get("code") or "")
  if exc.status_code == 409:
    if any(token in text for token in (
      "supplyshippingrequired",
      "supply shipping required",
      "shipping point",
      "shippingpoint",
      "shippingdt",
      "shipping type",
      "supplyshipping",
    )):
      return (
        "WB не видит параметры отгрузки (пункт, дата, способ). "
        "Откройте окно «В доставку», заново выберите пункт из списка и дату, затем повторите."
      )
    if any(token in text for token in (
      "metavalidationfail",
      "sgtin",
      "marking",
      "uin",
      "imei",
      "customsdeclaration",
      " meta ",
    )):
      meta_hint = _format_meta_validation_orders(payload)
      return (
        "WB отклонил передачу в доставку: не пройдена проверка маркировки/метаданных "
        f"в поставке.{meta_hint} "
        "Проверьте ЧЗ, УИН, IMEI или ДТ — замените товар или дождитесь проверки WB."
      )
    if any(token in text for token in ("supplyalreadyscanned", "already delivered", "already scanned")):
      return (
        "WB уже принял эту поставку. Нажмите «Обновить заказы» — CRM синхронизирует статус."
      )
    if any(token in text for token in ("supplyhaszeroorders", "zero orders")):
      return (
        "WB не видит заказов в поставке. Нажмите «Обновить заказы» или отправьте заказы на сборку заново."
      )
    if any(token in text for token in ("statusmismatch", "statuschange")):
      return (
        "WB отклонил передачу: один или несколько заказов не в статусе «На сборке». "
        "Нажмите «Обновить заказы» и повторите."
      )
    if code:
      return f"WB отклонил передачу в доставку ({code}): {exc}"
    return f"WB отклонил передачу в доставку: {exc}"
  return str(exc)


def _validate_shipping_date(shipping_date: date) -> None:
  today_moscow = timezone.now().astimezone(MOSCOW_TZ).date()
  if shipping_date < today_moscow:
    raise SupplyFlowError(
      f"Дата отгрузки {shipping_date.isoformat()} уже прошла по московскому времени. "
      "Выберите сегодня или более позднюю дату.",
      code="invalid_shipping_date",
    )


def _assert_wb_supply_shipping_applied(
  client,
  supply: Supply,
  *,
  shipping_point_id: int,
  shipping_date: date,
) -> None:
  """Убедиться, что WB сохранил пункт и дату отгрузки перед deliver."""
  try:
    raw = client.fetch_supply(supply.wb_supply_id)
  except WBApiError as exc:
    raise SupplyFlowError(
      "WB не подтвердил пункт отгрузки — повторите передачу в доставку "
      f"или выберите другой пункт (#{shipping_point_id}).",
      code="wb_shipping_verify_failed",
    ) from exc
  details = _unwrap_wb_supply_dict(raw if isinstance(raw, dict) else {})
  wb_point = details.get("shippingPointId")
  wb_date = str(details.get("shippingDt") or "").strip()[:10]
  expected_date = shipping_date.isoformat()
  if wb_point is None or int(wb_point) != int(shipping_point_id) or wb_date != expected_date:
    raise SupplyFlowError(
      "WB не сохранил параметры отгрузки для поставки "
      f"{supply.wb_supply_id}. Выбрали #{shipping_point_id}, "
      f"в WB сейчас #{wb_point or '—'}. Выберите пункт из актуального списка "
      "и повторите передачу в доставку.",
      code="wb_shipping_not_applied",
    )


def _assert_wb_supply_orders_ready(client, supply: Supply) -> None:
  """Сверить состав поставки в WB — deliver падает 409, если там есть «битые» заказы."""
  wb_ids = client.fetch_supply_order_ids(supply.wb_supply_id)
  if not wb_ids:
    raise SupplyFlowError(
      f"WB не видит заказов в поставке {supply.wb_supply_id}. "
      "Нажмите «Обновить заказы» или отправьте заказы на сборку заново.",
      code="not_ready",
    )
  try:
    statuses = client.fetch_order_statuses(wb_ids)
  except WBApiError as exc:
    logger.warning("WB order status preflight failed supply=%s: %s", supply.wb_supply_id, exc)
    return
  bad: list[str] = []
  for item in statuses:
    if not isinstance(item, dict):
      continue
    raw_id = item.get("id") or item.get("orderId") or item.get("orderID")
    supplier = str(item.get("supplierStatus") or "").strip()
    if supplier and supplier != WB_SUPPLIER_ASSEMBLY:
      bad.append(f"#{raw_id} ({supplier})")
  if bad:
    sample = ", ".join(bad[:4])
    extra = f" и ещё {len(bad) - 4}" if len(bad) > 4 else ""
    raise SupplyFlowError(
      "WB не даст передать поставку в доставку: в ней есть заказы не в статусе «На сборке»: "
      f"{sample}{extra}. Перенесите или удалите их в ЛК WB, затем «Обновить заказы».",
      code="wb_supply_orders_not_confirm",
    )
  try:
    meta_items = client.fetch_orders_meta(wb_ids)
  except WBApiError as exc:
    logger.warning("WB orders/meta preflight failed supply=%s: %s", supply.wb_supply_id, exc)
    return
  from apps.orders.services.marking import parse_marking_verify_decision
  from apps.orders.services.marking_verification import _extract_sgtin_decision

  meta_by_id: dict[int, dict] = {}
  for item in meta_items:
    raw_id = item.get("id") or item.get("orderId") or item.get("order_id")
    if raw_id is None:
      continue
    try:
      meta_by_id[int(raw_id)] = item
    except (TypeError, ValueError):
      continue
  blocked: list[str] = []
  for wb_id in wb_ids:
    item = meta_by_id.get(int(wb_id))
    if not item:
      continue
    for detail in item.get("metaDetails") or item.get("meta_details") or []:
      if not isinstance(detail, dict):
        continue
      decision = str(detail.get("decision") or detail.get("status") or "").strip()
      if not decision:
        continue
      status, _ = parse_marking_verify_decision(decision)
      if status in (VERIFY_PENDING, VERIFY_ERROR):
        key = str(detail.get("key") or "meta")
        blocked.append(f"#{wb_id} ({key}={decision})")
        break
    else:
      sgtin_decision = _extract_sgtin_decision(item)
      if sgtin_decision:
        status, _ = parse_marking_verify_decision(sgtin_decision)
        if status in (VERIFY_PENDING, VERIFY_ERROR):
          blocked.append(f"#{wb_id} (sgtin={sgtin_decision})")
  if blocked:
    sample = ", ".join(blocked[:4])
    extra = f" и ещё {len(blocked) - 4}" if len(blocked) > 4 else ""
    raise SupplyFlowError(
      "WB не даст передать поставку: маркировка не прошла проверку или ещё проверяется: "
      f"{sample}{extra}. Исправьте ЧЗ/метаданные и повторите.",
      code="marking_not_ready",
    )


def parse_wb_supply_move_error(exc: WBApiError) -> str:
  """Понятная причина, почему WB не даёт перенести заказ в другую поставку."""
  text = f"{exc} {getattr(exc, 'code', '')}".lower()
  if any(token in text for token in ("cargotype", "cargo_type", "cargo type", "габарит", "тип груза")):
    return (
      "WB не принял перенос: у заказа другой тип груза (обычный / крупногабарит), "
      "чем у выбранной поставки. Создайте новую пустую поставку."
    )
  if any(token in text for token in ("warehouse", "склад", "officeid", "office_id")):
    return (
      "WB не принял перенос: заказ с другого склада FBS. "
      "Нужна поставка того же склада или новая пустая."
    )
  if "b2b" in text:
    return (
      "WB не принял перенос: нельзя смешивать заказы B2B и обычные в одной поставке. "
      "Создайте новую пустую поставку."
    )
  if any(token in text for token in ("crossborder", "cross_border", "кроссбордер")):
    return (
      "WB не принял перенос: нельзя смешивать кроссбордер и обычные заказы. "
      "Создайте новую пустую поставку."
    )
  if any(token in text for token in ("closed", "done", "закрыт", "уже передан", "already delivered")):
    return (
      "WB уже закрыл текущую поставку. Заказ из неё нельзя перенести, "
      "пока он не появится в «повторной отгрузке». "
      "Отмените его в ЛК WB — тогда WB сам уберёт заказ из поставки."
    )
  if any(token in text for token in ("incorrectparameter", "incorrect parameter", "некорректный параметр")):
    return (
      "WB отклонил перенос (некорректный параметр). "
      "Чаще всего текущая поставка уже закрыта или заказ не в статусе «На сборке». "
      f"Ответ WB: {exc}"
    )
  if any(token in text for token in ("confirm", "supplierstatus", "статус")):
    return (
      "WB не даёт перенести заказ: он не в статусе «На сборке». "
      "Нажмите «Обновить заказы» и повторите."
    )
  if exc.status_code == 409:
    return (
      "WB не даёт перенести этот заказ. Отсутствие товара на складе тут ни при чём — "
      "409 значит конфликт поставки: текущая уже закрыта, или у другой другой склад / тип груза / B2B. "
      f"Ответ WB: {exc}"
    )
  return f"WB не принял перенос заказа в поставку: {exc}"


def _resolve_supply_cargo_type(client, supply: Supply) -> int:
  if not supply.wb_supply_id:
    return 1
  try:
    details = client.fetch_supply(supply.wb_supply_id)
    cargo = int(details.get("cargoType") or 1)
    return cargo if cargo in (1, 2, 3) else 1
  except WBApiError:
    return 1


SC_LIST_CARGO_TYPES = _shipping_catalog.SC_LIST_CARGO_TYPES
SHIPPING_POINTS_CACHE_VERSION = _shipping_catalog.SHIPPING_POINTS_CACHE_VERSION
SHIPPING_PREFETCH_NEAR_DONE_THRESHOLD = _shipping_catalog.SHIPPING_PREFETCH_NEAR_DONE_THRESHOLD
SHIPPING_PREFETCH_DEBOUNCE_SEC = _shipping_catalog.SHIPPING_PREFETCH_DEBOUNCE_SEC
SHIPPING_SUPPLY_PREFETCH_FLAG_TTL = _shipping_catalog.SHIPPING_SUPPLY_PREFETCH_FLAG_TTL
ALL_SC_SHIPPING_CACHE_TTL = _shipping_catalog.ALL_SC_SHIPPING_CACHE_TTL

_seller_shipping_cache_key = _shipping_catalog._seller_shipping_cache_key


def _shipping_prefetch_lock_key(seller_id: int, wb_supply_id: str | None = None) -> str:
  return _shipping_catalog.shipping_prefetch_lock_key(seller_id, wb_supply_id)


def _reference_wb_seller_for_fulfillment(user) -> Seller:
  from apps.accounts.tenant import get_user_fulfillment, sellers_for_user

  fulfillment = get_user_fulfillment(user)
  if not fulfillment:
    raise SupplyFlowError("Фулфилмент не определён", code="no_fulfillment")
  seller = (
    sellers_for_user(user)
    .filter(is_active=True)
    .exclude(wb_api_token_encrypted="")
    .order_by("id")
    .first()
  )
  if not seller or not seller.wb_api_token_encrypted:
    raise SupplyFlowError(
      "Нет активного селлера с токеном WB для загрузки пунктов отгрузки",
      code="no_wb_token",
    )
  return seller


def _shipping_points_no_fulfillment(exc: ValueError) -> None:
  if str(exc) == "no_fulfillment":
    raise SupplyFlowError("У селлера не указан фулфилмент", code="no_fulfillment") from exc
  raise exc


def fetch_seller_shipping_points(
  seller: Seller,
  *,
  city: str,
  cargo_type: int | None = None,
  wb_supply_id: str | None = None,
) -> tuple[list[dict], list[dict], int]:
  """Пункты отгрузки WB для модалки «В доставку» (только СЦ и склады)."""
  city = (city or "").strip()
  if not city:
    raise SupplyFlowError("Укажите город для поиска пунктов отгрузки", code="invalid_city")
  try:
    return _shipping_catalog.fetch_seller_shipping_points(
      seller,
      city=city,
      cargo_type=cargo_type,
      wb_supply_id=wb_supply_id,
    )
  except ValueError as exc:
    _shipping_points_no_fulfillment(exc)


def fetch_moscow_region_sc_shipping_points(
  seller: Seller,
  *,
  cargo_type: int | None = None,
  wb_supply_id: str | None = None,
  force_refresh: bool = False,
  cache_only: bool = False,
) -> tuple[list[dict], list[dict], int]:
  """СЦ и склады WB: Москва и МО ~50 км — только ответ API селлера."""
  try:
    return _shipping_catalog.fetch_moscow_region_sc_shipping_points(
      seller,
      cargo_type=cargo_type,
      wb_supply_id=wb_supply_id,
      force_refresh=force_refresh,
      cache_only=cache_only,
    )
  except ValueError as exc:
    _shipping_points_no_fulfillment(exc)


def count_supply_orders_pending_scan(supply: Supply, seller: Seller) -> int:
  """Сколько заказов поставки ещё не отсканированы (стикер не напечатан в CRM)."""
  return sum(
    1
    for order in assembly_supply_orders(supply, seller)
    if not order_sticker_printed_in_crm(order)
  )


def _active_forming_supplies_for_order(order: Order, seller: Seller) -> list[Supply]:
  return list(
    Supply.objects.filter(
      seller=seller,
      orders=order,
      status__in=(Supply.Status.FORMING, Supply.Status.READY),
    ).exclude(wb_supply_id="")
  )


def schedule_shipping_points_prefetch(
  seller: Seller,
  *,
  wb_supply_id: str | None = None,
  force_refresh: bool = False,
) -> None:
  """Фоновая подгрузка пунктов отгрузки WB токеном селлера."""
  if not seller.wb_api_token_encrypted:
    return
  from apps.integrations.tasks import prefetch_seller_shipping_points_task

  prefetch_seller_shipping_points_task.delay(
    seller.id,
    wb_supply_id=wb_supply_id or "",
    force_refresh=force_refresh,
  )


def prefetch_seller_shipping_points_sync(
  seller_id: int,
  *,
  wb_supply_id: str | None = None,
  force_refresh: bool = False,
) -> dict:
  seller = Seller.objects.filter(pk=seller_id, is_active=True).first()
  if not seller or not seller.wb_api_token_encrypted:
    return {"success": False, "detail": "seller_or_token_missing"}
  sc_points, _pp_points, resolved_cargo = fetch_moscow_region_sc_shipping_points(
    seller,
    wb_supply_id=wb_supply_id,
    force_refresh=force_refresh,
  )
  return {
    "success": True,
    "seller_id": seller.id,
    "wb_supply_id": wb_supply_id or "",
    "cargo_type": resolved_cargo,
    "sc_count": len(sc_points),
    "pp_count": 0,
  }


def maybe_prefetch_shipping_points_after_assembly_progress(
  seller: Seller,
  order: Order | None = None,
  *,
  on_assembly_start: bool = False,
  wb_supply_ids: list[str] | None = None,
) -> None:
  """
  Сразу после «На сборку» — фоновая подгрузка СЦ в кэш (общий + по поставкам).
  При «В доставку» список берётся из кэша, без повторного обхода WB по городам.
  """
  if not on_assembly_start or not seller.wb_api_token_encrypted:
    return

  if cache.add(
    _shipping_prefetch_lock_key(seller.id),
    "1",
    SHIPPING_PREFETCH_DEBOUNCE_SEC,
  ):
    schedule_shipping_points_prefetch(seller)

  supply_ids: set[str] = set()
  for raw_id in wb_supply_ids or []:
    normalized = str(raw_id or "").strip()
    if normalized:
      supply_ids.add(normalized)
  if order is not None:
    for supply in _active_forming_supplies_for_order(order, seller):
      normalized = str(supply.wb_supply_id or "").strip()
      if normalized:
        supply_ids.add(normalized)

  for wb_supply_id in supply_ids:
    lock_key = _shipping_prefetch_lock_key(seller.id, wb_supply_id)
    if not cache.add(lock_key, "1", SHIPPING_SUPPLY_PREFETCH_FLAG_TTL):
      continue
    schedule_shipping_points_prefetch(
      seller,
      wb_supply_id=wb_supply_id,
      force_refresh=False,
    )


def fetch_fulfillment_shipping_points_catalog(
  user,
  *,
  seller: Seller | None = None,
  cargo_type: int | None = None,
  wb_supply_id: str | None = None,
  force_refresh: bool = False,
) -> dict:
  """Справочник пунктов отгрузки WB для фулфилмента (без отправки в доставку)."""
  from apps.accounts.tenant import get_user_fulfillment

  fulfillment = get_user_fulfillment(user)
  if not fulfillment:
    raise SupplyFlowError("Фулфилмент не определён", code="no_fulfillment")

  reference = seller
  if not reference or not reference.wb_api_token_encrypted:
    reference = _reference_wb_seller_for_fulfillment(user)

  client = _get_client(reference)
  resolved_cargo = _shipping_catalog.resolve_shipping_cargo_type(
    client,
    cargo_type=cargo_type,
    wb_supply_id=wb_supply_id,
  )
  cache_key = _seller_shipping_cache_key(
    reference.id,
    resolved_cargo,
    wb_supply_id=wb_supply_id,
  )
  cached_before = cache.get(cache_key) if not force_refresh else None
  from_cache = (
    isinstance(cached_before, dict)
    and isinstance(cached_before.get("sc"), list)
    and not force_refresh
  )

  sc_points, _pp_points, resolved_cargo = fetch_moscow_region_sc_shipping_points(
    reference,
    cargo_type=cargo_type,
    wb_supply_id=wb_supply_id,
    force_refresh=force_refresh,
  )
  cached_after = cache.get(cache_key)
  cached_at = cached_after.get("cached_at") if isinstance(cached_after, dict) else None

  return {
    "success": True,
    "city": "Москва и Московская область (~50 км)",
    "scope": "all_sc",
    "cargo_type": resolved_cargo,
    "fulfillment_id": fulfillment.id,
    "reference_seller_id": reference.id,
    "reference_seller_name": reference.company_name,
    "from_cache": from_cache,
    "cached_at": cached_at,
    "cache_ttl_sec": ALL_SC_SHIPPING_CACHE_TTL,
    "shipping_points_sc": [_serialize_shipping_point_for_api(item) for item in sc_points],
    "shipping_points_pp": [],
    "shipping_points": [_serialize_shipping_point_for_api(item) for item in sc_points],
  }


def fetch_all_russia_sc_shipping_points(
  seller: Seller,
  *,
  cargo_type: int | None = None,
  wb_supply_id: str | None = None,
  force_refresh: bool = False,
  cache_only: bool = False,
) -> tuple[list[dict], list[dict], int]:
  """Обратная совместимость scope=all_sc → Москва и МО (СЦ и склады)."""
  return fetch_moscow_region_sc_shipping_points(
    seller,
    cargo_type=cargo_type,
    wb_supply_id=wb_supply_id,
    force_refresh=force_refresh,
    cache_only=cache_only,
  )


def _serialize_shipping_point_for_api(point: dict) -> dict:
  return _shipping_catalog.serialize_shipping_point_for_api(point)


def _apply_shipping_method(
  client,
  supply: Supply,
  *,
  shipping_point_id: int,
  shipping_date: date,
  shipping_type: str = "selfShipping",
) -> None:
  if not supply.wb_supply_id:
    raise SupplyFlowError("У поставки нет ID WB", code="no_supply")
  _validate_shipping_date(shipping_date)
  logger.info(
    "WB set shipping point supply=%s point_id=%s date=%s",
    supply.wb_supply_id,
    shipping_point_id,
    shipping_date.isoformat(),
  )
  try:
    client.set_supplies_shipping_method([{
      "supplyId": supply.wb_supply_id,
      "shippingPointId": shipping_point_id,
      "shippingDt": shipping_date.isoformat(),
      "shippingType": shipping_type,
    }])
  except WBApiError as exc:
    raise SupplyFlowError(
      _parse_shipping_method_error(exc),
      code="wb_shipping_method_failed",
    ) from exc


def _prepare_wb_supply_deliver(
  client,
  supply: Supply,
  *,
  shipping_point_id: int,
  shipping_date: date,
  shipping_type: str = "selfShipping",
) -> bool:
  """
  Установить параметры отгрузки и проверить поставку в WB.
  Возвращает True, если поставка уже закрыта в WB (deliver вызывать не нужно).
  """
  if not supply.wb_supply_id:
    raise SupplyFlowError("У поставки нет ID WB", code="no_supply")
  try:
    raw = client.fetch_supply(supply.wb_supply_id)
  except WBApiError as exc:
    logger.warning("WB fetch_supply before deliver failed supply=%s: %s", supply.wb_supply_id, exc)
    raw = {}
  details = _unwrap_wb_supply_dict(raw if isinstance(raw, dict) else {})
  if _wb_supply_closed(details):
    wb_point = details.get("shippingPointId")
    if wb_point is not None and int(wb_point) != int(shipping_point_id):
      raise SupplyFlowError(
        "Поставка уже закрыта в WB на другой пункт отгрузки "
        f"(#{wb_point}, вы выбрали #{shipping_point_id}). "
        "Сменить СЦ после передачи в доставку нельзя.",
        code="wb_shipping_locked",
      )
    return True
  _apply_shipping_method(
    client,
    supply,
    shipping_point_id=shipping_point_id,
    shipping_date=shipping_date,
    shipping_type=shipping_type,
  )
  _assert_wb_supply_shipping_applied(
    client,
    supply,
    shipping_point_id=shipping_point_id,
    shipping_date=shipping_date,
  )
  sync_supply_marking_from_wb(supply.seller, supply, client=client)
  _assert_wb_supply_orders_ready(client, supply)
  return False


def _ensure_marking_verified_for_delivery(seller: Seller, order: Order, *, user=None) -> None:
  """Перед доставкой — свежий опрос WB по ЧЗ, если в CRM ещё не подтверждено."""
  if not resolve_product_requires_marking(order.product, order.barcode, order.seller):
    return
  if order_marking_ready(order):
    return
  if not (order.marking_code or "").strip():
    raise SupplyFlowError(
      "Сначала отсканируйте и привяжите Честный знак (DataMatrix).",
      code="marking_required",
    )
  try:
    verify_marking_orders(seller, [order.id], user=user)
  except AssemblyError as exc:
    raise SupplyFlowError(str(exc), code="marking_verify_failed") from exc
  order.refresh_from_db()
  verify_status = (order.marking_verify_status or "").strip()
  if verify_status == VERIFY_ERROR:
    raise SupplyFlowError(
      order.marking_verify_error
      or "ЧЗ отклонён WB — замените товар и отсканируйте другой экземпляр.",
      code="marking_error",
    )
  if verify_status == VERIFY_PENDING:
    raise SupplyFlowError(
      "WB ещё проверяет Честный знак (обычно несколько минут). "
      "Дождитесь подтверждения или нажмите «Обновить из WB».",
      code="marking_pending",
    )
  if not order_marking_ready(order):
    raise SupplyFlowError(
      "Честный знак не подтверждён WB — нельзя передать в доставку.",
      code="marking_not_ready",
    )


def _supply_open_in_wb(client, supply: Supply) -> bool:
  """Поставка в WB ещё открыта — можно добавлять заказы на сборку."""
  if not supply.wb_supply_id:
    return False
  try:
    details = client.fetch_supply(supply.wb_supply_id)
  except WBApiError as exc:
    logger.warning(
      "WB fetch_supply failed supply=%s: %s",
      supply.wb_supply_id,
      exc,
    )
    return False
  if not isinstance(details, dict):
    return False
  if _wb_supply_closed(details):
    return False
  if _wb_supply_cargo(details) != 0:
    return False
  return True


def _get_or_create_forming_supply(
  seller: Seller,
  wb_warehouse_id: int,
  client,
) -> Supply:
  """Одна формирующаяся поставка WB на склад (только открытая в ЛК WB)."""
  candidates = (
    Supply.objects.filter(
      seller=seller,
      wb_warehouse_id=wb_warehouse_id,
      status=Supply.Status.FORMING,
    )
    .exclude(wb_supply_id="")
    .order_by("-created_at")
  )
  for supply in candidates:
    if _supply_open_in_wb(client, supply):
      return supply

  supply_name = f"CRM-S{seller.id}-W{wb_warehouse_id}-{timezone.now():%Y%m%d%H%M}"
  wb_supply_id = client.create_supply(supply_name)
  time.sleep(SUPPLY_CREATE_SETTLE_SEC)
  return Supply.objects.create(
    seller=seller,
    wb_supply_id=wb_supply_id,
    wb_warehouse_id=wb_warehouse_id,
    status=Supply.Status.FORMING,
  )


def _create_new_forming_supply(
  seller: Seller,
  wb_warehouse_id: int,
  client,
) -> Supply:
  """Новая пустая поставка WB на склад (перенос неотсканированных заказов)."""
  supply_name = f"CRM-S{seller.id}-W{wb_warehouse_id}-{timezone.now():%Y%m%d%H%M%S}"
  wb_supply_id = client.create_supply(supply_name)
  return Supply.objects.create(
    seller=seller,
    wb_supply_id=wb_supply_id,
    wb_warehouse_id=wb_warehouse_id,
    status=Supply.Status.FORMING,
  )


def _wb_supply_cargo(item: dict) -> int:
  try:
    return int(item.get("cargoType") or 0)
  except (TypeError, ValueError):
    return 0


def _wb_supply_closed(item: dict) -> bool:
  if not item:
    return False
  if item.get("done") in (True, "true", "True", 1, "1"):
    return True
  return bool(item.get("closedAt"))


def _wb_supply_open(item: dict) -> bool:
  return not _wb_supply_closed(item)


def _fetch_reshipment_ids(client) -> set[int]:
  try:
    return set(client.fetch_reshipment_order_ids() or [])
  except WBApiError as exc:
    logger.warning("WB reshipment list failed: %s", exc)
    return set()


def _assert_orders_can_leave_supply(
  client,
  orders: list[Order],
  current_ids: set[str],
  *,
  listed_supplies: dict[str, dict] | None = None,
) -> dict:
  """Проверить в ЛК WB, что заказ ещё можно перенести из текущей поставки."""
  details_by_id: dict[str, dict] = dict(listed_supplies or {})
  status_by_id: dict[int, dict] = {}
  wb_ids = [int(order.wb_order_id) for order in orders]
  try:
    for item in client.fetch_order_statuses(wb_ids):
      raw = item.get("id") or item.get("orderId") or item.get("orderID")
      if raw is None:
        continue
      try:
        status_by_id[int(raw)] = item if isinstance(item, dict) else {}
      except (TypeError, ValueError):
        continue
  except WBApiError as exc:
    logger.warning("WB order status check failed: %s", exc)

  reshipment_ids: set[int] | None = None

  def reshipment() -> set[int]:
    nonlocal reshipment_ids
    if reshipment_ids is None:
      reshipment_ids = _fetch_reshipment_ids(client)
    return reshipment_ids

  for order in orders:
    item = status_by_id.get(int(order.wb_order_id), {})
    supplier = (item.get("supplierStatus") or "").strip()
    if supplier in CANCEL_SUPPLIER_STATUSES:
      raise SupplyFlowError(
        f"WB уже отменил заказ #{order.wb_order_id}. Переносить некуда — нажмите «Обновить заказы».",
        code="order_cancelled",
      )
    if supplier == WB_SUPPLIER_DELIVERY and int(order.wb_order_id) not in reshipment():
      raise SupplyFlowError(
        f"WB уже перевёл заказ #{order.wb_order_id} в доставку. "
        "Из закрытой поставки его можно перенести только если он в «повторной отгрузке».",
        code="order_already_complete",
      )

  for supply_id in current_ids:
    details = details_by_id.get(supply_id)
    if not details:
      try:
        details = client.fetch_supply(supply_id)
      except WBApiError as exc:
        if exc.status_code == 404:
          continue
        raise SupplyFlowError(
          f"Не удалось проверить поставку {supply_id} в ЛК WB: {exc}",
          code="wb_supply_check_failed",
        ) from exc
    details_by_id[supply_id] = details if isinstance(details, dict) else {}
    if not _wb_supply_closed(details_by_id[supply_id]):
      continue
    not_reship = [order for order in orders if int(order.wb_order_id) not in reshipment()]
    if not not_reship:
      continue
    raise SupplyFlowError(
      f"WB уже закрыл поставку {supply_id}. Заказ из закрытой поставки нельзя перенести, "
      "пока он не появится в «повторной отгрузке». "
      "Отмените недостающий заказ в ЛК WB — WB сам уберёт его из поставки, "
      "и собранные можно будет отгрузить.",
      code="source_supply_closed",
    )
  return details_by_id


def _warehouse_name(seller: Seller, wb_warehouse_id: int | None) -> str:
  if wb_warehouse_id is None:
    return ""
  from apps.sellers.models import SellerWarehouse

  warehouse = SellerWarehouse.objects.filter(
    seller=seller,
    wb_warehouse_id=wb_warehouse_id,
  ).first()
  if warehouse and warehouse.name:
    return warehouse.name
  return f"Склад #{wb_warehouse_id}"


def _current_wb_supply_ids(orders: list[Order]) -> set[str]:
  ids: set[str] = set()
  for order in orders:
    for supply in order.supplies.filter(status__in=(Supply.Status.FORMING, Supply.Status.READY)):
      if supply.wb_supply_id:
        ids.add(str(supply.wb_supply_id))
  return ids


def _crm_supply_candidate_ok(supply: Supply) -> bool:
  if supply.status not in (Supply.Status.FORMING, Supply.Status.READY):
    return False
  if not supply.wb_supply_id:
    return False
  orders = _supply_orders(supply)
  if orders and all(order_can_send_to_delivery(order) for order in orders):
    return False
  if any(order_can_send_to_delivery(order) for order in orders):
    return False
  return True


def list_move_target_supplies(seller: Seller, order_ids: list[int]) -> list[dict]:
  """Пустые открытые поставки ЛК WB — заполненные чужие дают 409 (склад / груз / B2B)."""
  if not order_ids:
    raise SupplyFlowError("Не выбраны заказы для переноса", code="empty")

  orders = list(
    filter_orders_for_assembly(
      Order.objects.filter(seller=seller, pk__in=order_ids).prefetch_related("supplies"),
      seller,
    )
  )
  if not orders:
    raise SupplyFlowError("Заказы не найдены", code="not_found")

  current_ids = _current_wb_supply_ids(orders)
  warehouse_ids = {
    int(order.wb_warehouse_id)
    for order in orders
    if order.wb_warehouse_id is not None
  }
  crm_by_wb_id = {
    str(supply.wb_supply_id): supply
    for supply in filter_supplies_for_assembly(
      Supply.objects.filter(
        seller=seller,
        status__in=(Supply.Status.FORMING, Supply.Status.READY),
      ).exclude(wb_supply_id=""),
      seller,
    )
    if str(supply.wb_supply_id)
  }

  wb_by_id: dict[str, dict] = {}
  client = _get_client(seller)
  try:
    for item in client.fetch_supplies():
      raw_id = item.get("id")
      if raw_id is None or str(raw_id).strip() == "":
        continue
      wb_by_id[str(raw_id)] = item
  except WBApiError as exc:
    raise SupplyFlowError(
      f"Не удалось получить поставки из ЛК WB: {exc}",
      code="wb_supplies_failed",
    ) from exc

  _assert_orders_can_leave_supply(
    client,
    orders,
    current_ids,
    listed_supplies=wb_by_id,
  )

  targets: list[dict] = []
  seen: set[str] = set()
  for wb_id, item in wb_by_id.items():
    if wb_id in current_ids or wb_id in seen:
      continue
    if not _wb_supply_open(item):
      continue
    # Только пустые: в заполненную чужую поставку WB отвечает 409.
    if _wb_supply_cargo(item) != 0:
      continue
    crm = crm_by_wb_id.get(wb_id)
    if crm and not _crm_supply_candidate_ok(crm):
      continue
    if crm and warehouse_ids and crm.wb_warehouse_id is not None and int(crm.wb_warehouse_id) not in warehouse_ids:
      continue
    seen.add(wb_id)
    warehouse_id = crm.wb_warehouse_id if crm else (next(iter(warehouse_ids), None))
    targets.append({
      "wb_supply_id": wb_id,
      "name": f"Поставка WB {wb_id}",
      "orders_count": crm.orders.count() if crm else 0,
      "wb_warehouse_id": warehouse_id,
      "warehouse_name": _warehouse_name(seller, warehouse_id),
    })
  return targets


def _resolve_move_target_supply(
  seller: Seller,
  wb_warehouse_id: int,
  client,
  *,
  target_wb_supply_id: str | None,
  current_wb_ids: set[str],
) -> Supply:
  requested = (target_wb_supply_id or "").strip()
  if not requested:
    return _create_new_forming_supply(seller, wb_warehouse_id, client)
  if requested in current_wb_ids:
    raise SupplyFlowError(
      "Нельзя перенести заказ в ту же поставку. Выберите другую поставку в ЛК WB или создайте новую.",
      code="same_supply",
    )

  supply = Supply.objects.filter(seller=seller, wb_supply_id=requested).first()
  if supply:
    if not _crm_supply_candidate_ok(supply):
      raise SupplyFlowError(
        "Эта поставка уже готова к доставке или закрыта. Выберите другую или создайте новую.",
        code="supply_not_open",
      )
    return supply

  try:
    details = client.fetch_supply(requested)
  except WBApiError as exc:
    raise SupplyFlowError(
      f"Поставка {requested} не найдена в ЛК WB.",
      code="supply_not_found",
    ) from exc
  if details.get("done"):
    raise SupplyFlowError(
      "Эта поставка уже передана в доставку в ЛК WB. Выберите другую или создайте новую.",
      code="supply_done",
    )
  return Supply.objects.create(
    seller=seller,
    wb_supply_id=requested,
    wb_warehouse_id=wb_warehouse_id,
    status=Supply.Status.FORMING,
  )


def order_can_move_to_new_supply(order: Order) -> bool:
  """Несобранный заказ на обслуживаемом складе — можно перенести в другую поставку."""
  if order.wb_warehouse_id is None:
    return False
  if (order.wb_supplier_status or "").strip() != WB_SUPPLIER_ASSEMBLY:
    return False
  if order.status in (
    Order.Status.CANCELLED,
    Order.Status.SHIPPED,
    Order.Status.IN_DELIVERY,
  ):
    return False
  if order_sticker_printed_in_crm(order):
    return False
  if seller_has_warehouse_config(order.seller):
    if int(order.wb_warehouse_id) not in get_enabled_wb_warehouse_ids(order.seller):
      return False
  return True


@transaction.atomic
def move_orders_to_new_supply(
  seller: Seller,
  order_ids: list[int],
  *,
  user=None,
  wb_supply_id: str | None = None,
) -> dict:
  if not order_ids:
    raise SupplyFlowError("Не выбраны заказы для переноса", code="empty")

  orders = list(
    filter_orders_for_assembly(
      Order.objects.filter(seller=seller, pk__in=order_ids).select_related("product", "seller"),
      seller,
    )
  )
  if len(orders) != len(set(order_ids)):
    raise SupplyFlowError(
      "Некоторые заказы не найдены или с выключенного склада",
      code="not_found",
    )

  movable: list[Order] = []
  skipped: list[dict] = []
  for order in orders:
    if order_can_move_to_new_supply(order):
      movable.append(order)
    else:
      skipped.append({
        "order_id": order.id,
        "wb_order_id": order.wb_order_id,
        "error": "Заказ уже отсканирован или не на сборке",
      })

  if not movable:
    raise SupplyFlowError(
      "Нет заказов для переноса — можно переносить только неотсканированные на сборке",
      code="nothing_to_move",
    )

  by_warehouse: dict[int, list[Order]] = defaultdict(list)
  for order in movable:
    by_warehouse[int(order.wb_warehouse_id)].append(order)

  client = _get_client(seller)
  created_supplies: list[dict] = []
  target_id = (wb_supply_id or "").strip() or None

  for wb_warehouse_id, wh_orders in by_warehouse.items():
    current_ids = _current_wb_supply_ids(wh_orders)
    _assert_orders_can_leave_supply(client, wh_orders, current_ids)
    new_supply = _resolve_move_target_supply(
      seller,
      wb_warehouse_id,
      client,
      target_wb_supply_id=target_id,
      current_wb_ids=current_ids,
    )
    wb_order_ids = [int(order.wb_order_id) for order in wh_orders]
    created_now = str(new_supply.wb_supply_id) not in current_ids and not target_id
    if created_now:
      time.sleep(SUPPLY_CREATE_SETTLE_SEC)
    try:
      client.add_orders_to_supply(new_supply.wb_supply_id, wb_order_ids)
    except WBApiError as exc:
      retry_exc = exc
      if created_now or exc.status_code == 409:
        time.sleep(SUPPLY_CREATE_SETTLE_SEC)
        try:
          client.add_orders_to_supply(new_supply.wb_supply_id, wb_order_ids)
          retry_exc = None
        except WBApiError as second:
          retry_exc = second
      if retry_exc:
        if created_now and not new_supply.orders.exists():
          new_supply.delete()
        raise SupplyFlowError(
          parse_wb_supply_move_error(retry_exc),
          code="wb_move_failed",
        ) from retry_exc

    old_supply_ids: set[int] = set()
    for order in wh_orders:
      for old_supply in order.supplies.filter(
        status__in=(Supply.Status.FORMING, Supply.Status.READY),
      ):
        if str(old_supply.wb_supply_id) == str(new_supply.wb_supply_id):
          continue
        old_supply.orders.remove(order)
        old_supply_ids.add(old_supply.id)
      new_supply.orders.add(order)

    for old_supply_id in old_supply_ids:
      old_supply = Supply.objects.filter(pk=old_supply_id).first()
      if old_supply:
        refresh_supply_readiness(old_supply)
    refresh_supply_readiness(new_supply)

    created_supplies.append({
      "supply_id": new_supply.id,
      "wb_supply_id": new_supply.wb_supply_id,
      "wb_warehouse_id": wb_warehouse_id,
      "orders_moved": len(wh_orders),
      "created": not bool(target_id),
    })

  queue_last_pick_list_marking_verify(seller)

  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.SUPPLY,
    message=f"Перенос {len(movable)} заказов в {len(created_supplies)} новых поставок",
    details={
      "order_ids": [order.id for order in movable],
      "supplies": created_supplies,
      "skipped": skipped,
    },
  )

  return {
    "moved_count": len(movable),
    "supplies": created_supplies,
    "skipped": skipped,
  }


def _append_orders_to_forming_supply(
  seller: Seller,
  supply: Supply,
  orders: list[Order],
  *,
  client,
  user=None,
  skip_stickers: bool = False,
) -> tuple[int, str, list[Order], Supply]:
  """Добавить заказы в поставку WB. Возвращает (стикеры, ошибка, добавленные, поставка)."""
  existing_wb_ids = set(supply.orders.values_list("wb_order_id", flat=True))
  new_orders = [order for order in orders if order.wb_order_id not in existing_wb_ids]
  if not new_orders:
    return 0, "", [], supply

  wb_order_ids = [order.wb_order_id for order in new_orders]
  active_supply = supply
  last_exc: WBApiError | None = None
  for attempt in range(2):
    try:
      if not _supply_open_in_wb(client, active_supply):
        active_supply = _create_new_forming_supply(
          seller,
          int(active_supply.wb_warehouse_id),
          client,
        )
        time.sleep(SUPPLY_CREATE_SETTLE_SEC)
      client.add_orders_to_supply(active_supply.wb_supply_id, wb_order_ids)
      last_exc = None
      break
    except WBApiError as exc:
      last_exc = exc
      if exc.status_code != 409 or attempt == 1:
        raise
      logger.warning(
        "WB 409 adding orders to supply=%s, creating new supply seller=%s",
        active_supply.wb_supply_id,
        seller.id,
      )
      active_supply = _create_new_forming_supply(
        seller,
        int(active_supply.wb_warehouse_id),
        client,
      )
      time.sleep(SUPPLY_CREATE_SETTLE_SEC)
  if last_exc:
    raise last_exc

  active_supply.orders.add(*new_orders)

  for order in new_orders:
    order.status = Order.Status.IN_PICKING
    order.wb_supplier_status = WB_SUPPLIER_ASSEMBLY
    order.save(update_fields=["status", "wb_supplier_status", "updated_at"])

  if not skip_stickers:
    time.sleep(SUPPLY_CREATE_SETTLE_SEC)

  stickers_fetched = 0
  sticker_error = ""
  if not skip_stickers:
    try:
      stickers_fetched = fetch_stickers_for_orders(seller, new_orders, user=user)
      missing = [
        order for order in new_orders
        if not (order.sticker_file or "").strip()
      ]
      if missing:
        time.sleep(1.5)
        stickers_fetched += fetch_stickers_for_orders(seller, missing, user=user)
    except AssemblyError as exc:
      sticker_error = str(exc)

  return stickers_fetched, sticker_error, new_orders, active_supply


@transaction.atomic
def send_order_to_assembly(seller: Seller, order_id: int, *, user=None) -> dict:
  """
  Один заказ → поставка WB склада → статус confirm («На сборке»).
  Все заказы одного склада попадают в одну поставку.
  """
  order = _get_order(seller, order_id)

  if not order_can_send_to_assembly(order):
    raise SupplyFlowError(
      f"Заказ WB #{order.wb_order_id} нельзя отправить на сборку "
      f"(статус CRM: {order.get_status_display()}, WB: {order.wb_supplier_status or 'new'}).",
      code="invalid_status",
    )

  if order.wb_warehouse_id is None:
    raise SupplyFlowError(
      f"У заказа WB #{order.wb_order_id} не указан склад WB.",
      code="no_warehouse",
    )

  client = _get_client(seller)
  try:
    supply = _get_or_create_forming_supply(seller, order.wb_warehouse_id, client)
    stickers_fetched, sticker_error, added_orders, supply = _append_orders_to_forming_supply(
      seller,
      supply,
      [order],
      client=client,
      user=user,
    )
    if not added_orders:
      order.refresh_from_db()
      return {
        "order": order,
        "wb_supply_id": supply.wb_supply_id,
        "stickers_fetched": 0,
        "sticker_error": "",
      }
  except WBApiError as exc:
    AuditLog.objects.create(
      user=user,
      seller=seller,
      action_type=AuditLog.ActionType.API_ERROR,
      message=f"Ошибка отправки на сборку WB #{order.wb_order_id}: {exc}",
      details={"order_id": order.id, "status_code": exc.status_code},
    )
    raise SupplyFlowError(
      parse_wb_supply_move_error(exc),
      code="wb_assembly_failed",
    ) from exc

  order.refresh_from_db()

  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.ASSEMBLY,
    message=f"На сборку (WB): заказ #{order.wb_order_id}, поставка {supply.wb_supply_id}",
    details={
      "order_id": order.id,
      "wb_supply_id": supply.wb_supply_id,
      "wb_warehouse_id": order.wb_warehouse_id,
      "stickers_fetched": stickers_fetched,
      "sticker_error": sticker_error,
    },
  )

  if added_orders:
    from apps.orders.services.wb_status import remove_wb_orders_from_new_cache

    remove_wb_orders_from_new_cache(seller, [order.wb_order_id])
    seller.refresh_from_db(
      fields=[
        "wb_count_new",
        "wb_new_order_ids",
        "wb_count_assembly",
        "wb_count_delivery",
        "wb_counts_synced_at",
      ],
    )
    maybe_prefetch_shipping_points_after_assembly_progress(
      seller,
      order,
      on_assembly_start=True,
      wb_supply_ids=[supply.wb_supply_id],
    )

  return {
    "order": order,
    "wb_supply_id": supply.wb_supply_id,
    "stickers_fetched": stickers_fetched,
    "sticker_error": sticker_error,
    "orders_added": len(added_orders),
  }


def _fetch_supply_barcode_payload(client, wb_supply_id: str) -> tuple[str, str, str]:
  """ШК поставки WB доступен только после deliver; иногда API отвечает с задержкой."""
  supply_barcode_file = ""
  supply_barcode_value = ""
  last_error = ""
  for attempt in range(4):
    if attempt > 0:
      time.sleep(0.5 * attempt)
    try:
      barcode_payload = client.fetch_supply_barcode(wb_supply_id)
      if isinstance(barcode_payload, dict):
        supply_barcode_file = barcode_payload.get("file") or ""
        supply_barcode_value = str(barcode_payload.get("barcode") or "")
      if supply_barcode_file:
        return supply_barcode_file, supply_barcode_value, ""
    except WBApiError as exc:
      last_error = str(exc)
  return supply_barcode_file, supply_barcode_value, last_error


def _complete_order_in_delivery(
  order: Order,
  supply: Supply,
  *,
  seller: Seller,
  user=None,
) -> dict:
  """Перевести один заказ в «В доставке». Остаток списан при печати стикера."""
  order.status = Order.Status.IN_DELIVERY
  order.wb_supplier_status = WB_SUPPLIER_DELIVERY
  order.wb_status = WB_STATUS_AFTER_DELIVER
  if order.in_delivery_at is None:
    order.in_delivery_at = timezone.now()
  order.save(
    update_fields=[
      "status",
      "wb_supplier_status",
      "wb_status",
      "in_delivery_at",
      "updated_at",
    ],
  )
  stock_info = stock_deduction_info(order)
  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.SUPPLY,
    message=f"В доставку (WB): заказ #{order.wb_order_id}, поставка {supply.wb_supply_id}",
    details={
      "order_id": order.id,
      "wb_supply_id": supply.wb_supply_id,
    },
  )
  return stock_info


def _detach_order_from_pick_list(order: Order) -> None:
  from apps.orders.services.assembly import _detach_order_from_pick_list as detach

  if not order.pick_list_id:
    return
  detach(order)
  order.save(update_fields=["pick_list", "updated_at"])


def _complete_pick_lists_after_supply_delivery(supply: Supply, *, seller: Seller) -> None:
  """Архивировать листы подбора склада после передачи поставки в доставку."""
  qs = PickList.objects.filter(
    seller=seller,
    is_completed=False,
    marketplace="wb",
  )
  if supply.wb_warehouse_id is not None:
    qs = qs.filter(wb_warehouse_id=supply.wb_warehouse_id)
  now = timezone.now()
  for pick_list in qs:
    if pick_list.items.exists():
      pick_list.is_completed = True
      pick_list.completed_at = now
      pick_list.save(update_fields=["is_completed", "completed_at"])
    else:
      pick_list.delete()


def _assert_all_supply_orders_ready_for_deliver(supply: Supply, *, seller: Seller) -> None:
  orders = assembly_supply_orders(supply, seller)
  if not orders:
    raise SupplyFlowError("В поставке нет заказов на обслуживаемых складах", code="not_ready")
  not_ready = [order for order in orders if not order_can_send_to_delivery(order)]
  if not_ready:
    sample = not_ready[0]
    reason = order_delivery_block_reason(sample) or "не готов"
    raise SupplyFlowError(
      f"В поставке WB {supply.wb_supply_id} {len(not_ready)} из {len(orders)} "
      f"заказ(ов) ещё не готовы ({reason}). "
      "Дособерите все заказы или перенесите неготовые в другую поставку.",
      code="not_ready",
    )


def _detach_departed_orders_from_active_supply(supply: Supply, seller: Seller) -> int:
  """Открепить от активной поставки заказы, уже ушедшие с этапа сборки WB."""
  if supply.status not in (Supply.Status.FORMING, Supply.Status.READY):
    return 0
  to_remove = [
    order.id
    for order in supply.orders.filter(assembly_hidden=False).select_related("seller")
    if order_departed_wb_assembly(order)
  ]
  if not to_remove:
    return 0
  supply.orders.remove(*Order.objects.filter(pk__in=to_remove))
  return len(to_remove)


def _prepare_supply_orders_for_deliver(
  seller: Seller,
  supply: Supply,
  *,
  user=None,
  force: bool = False,
) -> None:
  sync_supply_marking_from_wb(seller, supply, user=user)
  for order in assembly_supply_orders(supply, seller):
    if not order_can_send_to_delivery(order):
      continue
    _ensure_marking_verified_for_delivery(seller, order, user=user)
    try:
      assert_order_stock_deducted_at_print(order)
    except StockDeductionError as exc:
      raise SupplyFlowError(str(exc), code="insufficient_stock") from exc
  if not force:
    _assert_all_supply_orders_ready_for_deliver(supply, seller=seller)


def _finalize_supply_after_wb_deliver(
  supply: Supply,
  *,
  seller: Seller,
  user=None,
  primary_order: Order | None = None,
) -> tuple[Order, dict]:
  """
  WB переводит в доставку всю поставку целиком — синхронизируем все заказы CRM
  и сразу убираем лист подбора.
  """
  last_order = primary_order
  last_stock: dict = {}
  for order in _supply_orders(supply):
    if order.status == Order.Status.IN_DELIVERY:
      _detach_order_from_pick_list(order)
      continue
    _detach_order_from_pick_list(order)
    last_stock = _complete_order_in_delivery(
      order,
      supply,
      seller=seller,
      user=user,
    )
    last_order = order
  _complete_pick_lists_after_supply_delivery(supply, seller=seller)
  if last_order is None:
    raise SupplyFlowError("В поставке нет заказов для CRM", code="not_ready")
  return last_order, last_stock


def _delivery_result(
  order: Order,
  supply: Supply,
  stock_info: dict,
  supply_barcode_file: str,
  supply_barcode_value: str,
  supply_barcode_error: str,
  *,
  seller: Seller,
  user=None,
  shipping_point_id: int | None = None,
  shipping_date: date | None = None,
) -> dict:
  if supply_barcode_error and not supply_barcode_file:
    AuditLog.objects.create(
      user=user,
      seller=seller,
      action_type=AuditLog.ActionType.API_ERROR,
      message=f"WB не вернул ШК поставки {supply.wb_supply_id}: {supply_barcode_error}",
      details={
        "order_id": order.id,
        "supply_id": supply.id,
        "wb_supply_id": supply.wb_supply_id,
      },
    )
  result = {
    "order": order,
    "supply_id": supply.id,
    "wb_supply_id": supply.wb_supply_id,
    "supply_barcode_file": supply_barcode_file,
    "supply_barcode": supply_barcode_value,
    "stock": stock_info,
  }
  if shipping_point_id is not None:
    result["shipping_point_id"] = int(shipping_point_id)
  if shipping_date is not None:
    result["shipping_date"] = shipping_date.isoformat()
  if supply_barcode_error and not supply_barcode_file:
    result["supply_barcode_error"] = supply_barcode_error
  return result


@transaction.atomic
def send_order_to_delivery(
  seller: Seller,
  order_id: int,
  *,
  user=None,
  shipping_point_id: int | None = None,
  shipping_date: date | None = None,
  shipping_type: str = "selfShipping",
) -> dict:
  """
  Один заказ → deliver поставки WB → complete+waiting («В доставке»).
  WB переводит в доставку всю поставку — в CRM обновляются все её заказы.
  """
  order = _get_order(seller, order_id)

  supply_qs = Supply.objects.filter(
    seller=seller,
    orders=order,
    status__in=(
      Supply.Status.FORMING,
      Supply.Status.READY,
      Supply.Status.CONFIRMED,
    ),
  ).exclude(wb_supply_id="")
  if order.wb_warehouse_id is not None:
    supply_qs = supply_qs.filter(wb_warehouse_id=order.wb_warehouse_id)
  supply = supply_qs.order_by("-created_at").first()
  if not supply:
    raise SupplyFlowError(
      f"Не найдена поставка WB для заказа #{order.wb_order_id} "
      f"на складе {order.wb_warehouse_id or '—'}. "
      "Отправьте заказ на сборку заново.",
      code="no_supply",
    )
  if (
    order.wb_warehouse_id is not None
    and supply.wb_warehouse_id is not None
    and supply.wb_warehouse_id != order.wb_warehouse_id
  ):
    raise SupplyFlowError(
      f"Поставка WB не соответствует складу заказа #{order.wb_order_id}.",
      code="warehouse_mismatch",
    )

  client = _get_client(seller)
  sync_supply_marking_from_wb(seller, supply, client=client, user=user)
  order.refresh_from_db()

  if not order_can_send_to_delivery(order):
    requires_marking = resolve_product_requires_marking(
      order.product, order.barcode, order.seller,
    )
    hint = ""
    if (order.marking_verify_status or "").strip() == VERIFY_ERROR:
      hint = f" {order.marking_verify_error or 'ЧЗ отклонён — замените товар.'}"
    elif requires_marking and not order.marking_bound:
      hint = " Сначала привяжите Честный знак и распечатайте стикер."
    elif requires_marking and (order.marking_verify_status or "").strip() == VERIFY_PENDING:
      hint = " WB ещё проверяет Честный знак — подождите несколько минут."
    elif order.status not in (Order.Status.LABEL_PRINTED, Order.Status.MARKED):
      hint = " Сначала отсканируйте баркод и распечатайте стикер FBS."
    raise SupplyFlowError(
      f"Заказ WB #{order.wb_order_id} не готов к отправке в доставку.{hint}",
      code="not_ready",
    )

  if order.status == Order.Status.IN_DELIVERY:
    raise SupplyFlowError(
      f"Заказ WB #{order.wb_order_id} уже передан в доставку.",
      code="already_delivered",
    )

  supply_barcode_file = ""
  supply_barcode_value = ""
  supply_barcode_error = ""

  if supply.status == Supply.Status.CONFIRMED:
    if not shipping_point_id or not shipping_date:
      raise SupplyFlowError(
        "Укажите пункт отгрузки (СЦ) и дату — CRM отправит их в WB перед печатью QR.",
        code="shipping_required",
      )
    _prepare_wb_supply_deliver(
      client,
      supply,
      shipping_point_id=shipping_point_id,
      shipping_date=shipping_date,
      shipping_type=shipping_type,
    )
    supply_barcode_file, supply_barcode_value, supply_barcode_error = _fetch_supply_barcode_payload(
      client,
      supply.wb_supply_id,
    )
    order, stock_info = _finalize_supply_after_wb_deliver(
      supply,
      seller=seller,
      user=user,
      primary_order=order,
    )
    _schedule_billing_refresh_after_delivery(seller)
    return _delivery_result(
      order,
      supply,
      stock_info,
      supply_barcode_file,
      supply_barcode_value,
      supply_barcode_error,
      user=user,
      seller=seller,
      shipping_point_id=shipping_point_id,
      shipping_date=shipping_date,
    )

  _prepare_supply_orders_for_deliver(seller, supply, user=user)

  try:
    if not shipping_point_id or not shipping_date:
      raise SupplyFlowError(
        "Укажите пункт отгрузки (СЦ/ПВЗ) и дату отгрузки — это обязательно для WB.",
        code="shipping_required",
      )
    already_delivered = _prepare_wb_supply_deliver(
      client,
      supply,
      shipping_point_id=shipping_point_id,
      shipping_date=shipping_date,
      shipping_type=shipping_type,
    )
    if not already_delivered:
      client.deliver_supply(supply.wb_supply_id)
  except WBApiError as exc:
    AuditLog.objects.create(
      user=user,
      seller=seller,
      action_type=AuditLog.ActionType.API_ERROR,
      message=f"Ошибка доставки WB #{order.wb_order_id}: {exc}",
      details={
        "order_id": order.id,
        "wb_supply_id": supply.wb_supply_id,
        "status_code": exc.status_code,
        "wb_code": getattr(exc, "code", ""),
        "wb_payload": getattr(exc, "payload", {}),
      },
    )
    raise SupplyFlowError(_parse_deliver_error(exc), code="wb_deliver_failed") from exc

  supply_barcode_file, supply_barcode_value, supply_barcode_error = _fetch_supply_barcode_payload(
    client,
    supply.wb_supply_id,
  )

  order, stock_info = _finalize_supply_after_wb_deliver(
    supply,
    seller=seller,
    user=user,
    primary_order=order,
  )

  supply.status = Supply.Status.CONFIRMED
  supply.supply_barcode_printed = bool(supply_barcode_file)
  supply.save(update_fields=["status", "supply_barcode_printed", "updated_at"])

  _schedule_billing_refresh_after_delivery(seller)
  return _delivery_result(
    order,
    supply,
    stock_info,
    supply_barcode_file,
    supply_barcode_value,
    supply_barcode_error,
    user=user,
    seller=seller,
    shipping_point_id=shipping_point_id,
    shipping_date=shipping_date,
  )


def delivery_stage_orders_queryset(seller: Seller) -> QuerySet:
  """Вкладка «В доставке»: complete + waiting — как в ЛК WB, только включённые FBS-склады."""
  return filter_orders_for_assembly(
    Order.objects.filter(seller=seller, assembly_hidden=False).filter(wb_in_delivery_q()),
    seller,
  )


def count_delivery_stage_orders(seller: Seller) -> int:
  return delivery_stage_orders_queryset(seller).count()


def delivery_stage_supplies_queryset(seller: Seller) -> QuerySet:
  """Поставки на вкладке «В доставке»: переданы в WB, ШК ещё не отсканирован на складе."""
  qs = Supply.objects.filter(
    seller=seller,
    status=Supply.Status.CONFIRMED,
    wb_scanned_at__isnull=True,
  ).exclude(wb_supply_id="")
  if seller_has_warehouse_config(seller):
    enabled = get_enabled_wb_warehouse_ids(seller)
    if not enabled:
      return qs.none()
    qs = qs.filter(wb_warehouse_id__in=enabled)
  return qs


def _active_assembly_supplies_qs(seller: Seller) -> QuerySet:
  return filter_supplies_for_assembly(
    Supply.objects.filter(
      seller=seller,
      status__in=(Supply.Status.FORMING, Supply.Status.READY),
    ),
    seller,
  )


def _wb_new_order_ids(seller: Seller) -> list[int]:
  raw = seller.wb_new_order_ids or []
  if not isinstance(raw, list):
    return []
  ids: list[int] = []
  for item in raw:
    try:
      ids.append(int(item))
    except (TypeError, ValueError):
      continue
  return ids


def new_stage_orders_queryset(seller: Seller) -> QuerySet:
  """Заказы вкладки «Новые» на странице сборки — как в ЛК WB + готовые к отправке."""
  base = filter_orders_for_assembly(
    Order.objects.filter(seller=seller, assembly_hidden=False),
    seller,
  )
  new_ids = _wb_new_order_ids(seller)
  terminal_statuses = [
    Order.Status.CANCELLED,
    Order.Status.SHIPPED,
    Order.Status.IN_DELIVERY,
  ]
  active_q = Q(wb_supplier_status=WB_SUPPLIER_NEW) & ~Q(status__in=terminal_statuses)
  if new_ids:
    active_q &= Q(wb_order_id__in=new_ids)
    cancelled_q = (
      Q(wb_order_id__in=new_ids)
      & Q(status=Order.Status.CANCELLED)
      & (
        Q(wb_supplier_status__in=CANCEL_SUPPLIER_STATUSES)
        | Q(wb_status__in=CANCEL_WB_STATUSES)
      )
    )
    return base.filter(active_q | cancelled_q)
  return base.filter(active_q)


def orders_at_risk_in_active_supplies(seller: Seller) -> QuerySet:
  """Заказы в активных поставках, которые ещё не отменены — для отслеживания отмен при sync."""
  supplies = _active_assembly_supplies_qs(seller)
  return Order.objects.filter(
    supplies__in=supplies,
    assembly_hidden=False,
  ).exclude(status=Order.Status.CANCELLED).distinct()


def cancelled_orders_in_active_supplies(seller: Seller, order_ids: list[int]) -> list[dict]:
  """Отменённые заказы из списка id, которые остались в активных поставках."""
  if not order_ids:
    return []
  active_statuses = (Supply.Status.FORMING, Supply.Status.READY)
  payload: list[dict] = []
  orders = (
    Order.objects.filter(
      seller=seller,
      id__in=order_ids,
      status=Order.Status.CANCELLED,
    )
    .prefetch_related("supplies")
  )
  for order in orders:
    supply = next(
      (item for item in order.supplies.all() if item.status in active_statuses),
      None,
    )
    if not supply:
      continue
    payload.append({
      "order_id": order.id,
      "wb_order_id": order.wb_order_id,
      "wb_supply_id": supply.wb_supply_id,
      "supply_id": supply.id,
    })
  return payload


def count_new_orders_for_barcode(seller: Seller, barcode: str) -> int:
  """Заказы вкладки «Новые» по баркоду на обслуживаемых FBS-складах."""
  barcode = (barcode or "").strip()
  if not barcode:
    return 0
  return new_stage_orders_queryset(seller).filter(barcode=barcode).count()


def count_new_orders_for_barcode_on_warehouse(
  seller: Seller,
  barcode: str,
  wb_warehouse_id: int | None,
) -> int:
  """Заказы «Новые» по баркоду на конкретном FBS-складе WB."""
  barcode = (barcode or "").strip()
  if not barcode or not wb_warehouse_id:
    return 0
  return new_stage_orders_queryset(seller).filter(
    barcode=barcode,
    wb_warehouse_id=wb_warehouse_id,
  ).count()


def picking_stage_orders_queryset(seller: Seller) -> QuerySet:
  """Заказы вкладки «На сборке» (confirm) на странице сборки."""
  base = filter_orders_for_assembly(
    Order.objects.filter(seller=seller, assembly_hidden=False),
    seller,
  )
  active_q = Q(wb_supplier_status=WB_SUPPLIER_ASSEMBLY) & ~Q(
    status__in=[Order.Status.CANCELLED, Order.Status.SHIPPED]
  )
  supplies = _active_assembly_supplies_qs(seller)
  if not supplies.exists():
    return base.filter(active_q)
  cancelled_q = (
    Q(supplies__in=supplies)
    & Q(status=Order.Status.CANCELLED)
    & (
      Q(wb_supplier_status__in=CANCEL_SUPPLIER_STATUSES)
      | Q(wb_status__in=CANCEL_WB_STATUSES)
    )
  )
  return base.filter(active_q | cancelled_q).distinct()


def count_picking_orders_for_barcode(seller: Seller, barcode: str) -> int:
  """Заказы вкладки «На сборке» по баркоду на обслуживаемых FBS-складах."""
  barcode = (barcode or "").strip()
  if not barcode:
    return 0
  return picking_stage_orders_queryset(seller).filter(barcode=barcode).count()


def count_picking_orders_for_barcode_on_warehouse(
  seller: Seller,
  barcode: str,
  wb_warehouse_id: int | None,
) -> int:
  """Заказы «На сборке» по баркоду на конкретном FBS-складе WB."""
  barcode = (barcode or "").strip()
  if not barcode or not wb_warehouse_id:
    return 0
  return picking_stage_orders_queryset(seller).filter(
    barcode=barcode,
    wb_warehouse_id=wb_warehouse_id,
  ).count()


def order_counts_by_barcode_on_warehouse(qs: QuerySet, wb_warehouse_id: int | None) -> dict[str, int]:
  """Счётчик заказов по баркоду на складе WB (одним запросом)."""
  from django.db.models import Count

  if not wb_warehouse_id:
    return {}
  rows = (
    qs.filter(wb_warehouse_id=wb_warehouse_id)
    .exclude(barcode="")
    .values("barcode")
    .annotate(n=Count("id"))
  )
  return {str(row["barcode"]): int(row["n"]) for row in rows if row.get("barcode")}


def count_orders_ready_for_assembly(seller: Seller) -> int:
  return new_stage_orders_queryset(seller).count()


def get_assembly_stage_counts(seller: Seller) -> dict[str, int]:
  """Счётчики вкладок сборки FBS — как в ЛК WB, только включённые FBS-склады."""
  from apps.orders.services.wb_status import get_wb_lk_tab_counts

  return get_wb_lk_tab_counts(seller)


def send_orders_to_assembly_bulk(
  seller: Seller,
  *,
  order_ids: list[int] | None = None,
  user=None,
  defer_stickers: bool = False,
) -> dict:
  """Отправить на сборку заказы: одна поставка WB на каждый склад."""
  qs = new_orders_ready_for_transfer_queryset(seller).select_related("product")
  if order_ids is not None:
    qs = qs.filter(pk__in=order_ids)

  orders = [order for order in qs if order_can_send_to_assembly(order)]
  if not orders:
    raise SupplyFlowError(
      "Нет готовых заказов для отправки на сборку. "
      "Дождитесь фоновой синхронизации (до 2 мин) или нажмите «Обновить заказы».",
      code="no_orders",
    )

  by_warehouse: dict[int, list[Order]] = defaultdict(list)
  errors: list[dict] = []
  for order in orders:
    if order.wb_warehouse_id is None:
      errors.append({
        "order_id": order.id,
        "wb_order_id": order.wb_order_id,
        "error": "Не указан склад WB",
      })
      continue
    by_warehouse[order.wb_warehouse_id].append(order)

  client = _get_client(seller)
  sent = 0
  stickers_total = 0
  sent_order_ids: list[int] = []
  sent_wb_order_ids: list[int] = []
  prefetch_supply_ids: list[str] = []

  for wb_warehouse_id, wh_orders in by_warehouse.items():
    try:
      supply = _get_or_create_forming_supply(seller, wb_warehouse_id, client)
      stickers_fetched, sticker_error, added_orders, supply = _append_orders_to_forming_supply(
        seller,
        supply,
        wh_orders,
        client=client,
        user=user,
        skip_stickers=defer_stickers,
      )
      sent += len(added_orders)
      stickers_total += stickers_fetched
      sent_order_ids.extend(order.id for order in added_orders)
      sent_wb_order_ids.extend(order.wb_order_id for order in added_orders)
      if supply.wb_supply_id:
        prefetch_supply_ids.append(supply.wb_supply_id)
      if sticker_error:
        errors.append({
          "wb_warehouse_id": wb_warehouse_id,
          "wb_supply_id": supply.wb_supply_id,
          "error": sticker_error,
        })
    except (SupplyFlowError, WBApiError) as exc:
      message = parse_wb_supply_move_error(exc) if isinstance(exc, WBApiError) else str(exc)
      for order in wh_orders:
        errors.append({
          "order_id": order.id,
          "wb_order_id": order.wb_order_id,
          "error": message,
        })

  if sent_order_ids and not defer_stickers:
    missing_stickers = list(
      Order.objects.filter(
        seller=seller,
        pk__in=sent_order_ids,
        wb_supplier_status=WB_SUPPLIER_ASSEMBLY,
      ).filter(
        Q(sticker_file="") | Q(sticker_file__isnull=True) | Q(has_sticker=False),
      ),
    )
    if missing_stickers:
      try:
        stickers_total += fetch_stickers_for_orders(
          seller,
          missing_stickers,
          user=user,
        )
      except AssemblyError as exc:
        errors.append({
          "error": f"Не все стикеры подтянулись из WB: {exc}",
          "still_missing": len(missing_stickers),
        })

  if sent == 0 and errors:
    raise SupplyFlowError(
      f"Не удалось отправить ни одного заказа. Пример: {errors[0]['error']}",
      code="batch_failed",
    )

  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.ASSEMBLY,
    message=(
      f"Массовая отправка на сборку: {sent} заказов, "
      f"поставок WB: {len(by_warehouse)}"
    ),
    details={
      "sent": sent,
      "total": len(orders),
      "supplies": len(by_warehouse),
      "errors": errors,
    },
  )

  if sent_wb_order_ids:
    from apps.orders.services.wb_status import remove_wb_orders_from_new_cache

    remove_wb_orders_from_new_cache(seller, sent_wb_order_ids)
    seller.refresh_from_db(
      fields=[
        "wb_count_new",
        "wb_new_order_ids",
        "wb_count_assembly",
        "wb_count_delivery",
        "wb_counts_synced_at",
      ],
    )

  if sent > 0 and orders:
    maybe_prefetch_shipping_points_after_assembly_progress(
      seller,
      orders[0],
      on_assembly_start=True,
      wb_supply_ids=prefetch_supply_ids,
    )

  return {
    "sent": sent,
    "total": len(orders),
    "supplies": len(by_warehouse),
    "stickers_fetched": stickers_total,
    "stickers_deferred": defer_stickers and sent > 0,
    "sent_order_ids": sent_order_ids,
    "sent_wb_order_ids": sent_wb_order_ids,
    "errors": errors,
  }


def order_delivery_block_reason(order: Order) -> str | None:
  if is_terminal_cancelled_order(order):
    return "Отменён в WB — удалите из CRM"
  if order_can_send_to_delivery(order):
    return None
  if (order.wb_supplier_status or "").strip() != WB_SUPPLIER_ASSEMBLY:
    return "Не на сборке WB"
  if not order_sticker_printed_in_crm(order):
    return "Нет стикера FBS — отсканируйте в сборке"
  if order.status not in (Order.Status.LABEL_PRINTED, Order.Status.MARKED):
    return "Нет стикера FBS — отсканируйте в сборке"
  verify_status = (order.marking_verify_status or "").strip()
  if verify_status == "error":
    return order.marking_verify_error or "ЧЗ отклонён WB — замените товар"
  if resolve_product_requires_marking(order.product, order.barcode, order.seller):
    if verify_status == "pending":
      return "WB проверяет ЧЗ (несколько минут) — в доставку после подтверждения WB"
    if not order_marking_ready(order):
      return "Нужен Честный знак"
  return "Не готов к доставке"


def _supply_orders(supply: Supply) -> list[Order]:
  return list(
    supply.orders.select_related("product", "seller").all(),
  )


def assembly_supply_orders(supply: Supply, seller: Seller) -> list[Order]:
  """Заказы поставки для доставки: без скрытых, отменённых и уже ушедших с сборки WB."""
  orders = filter_orders_for_assembly(
    supply.orders.filter(assembly_hidden=False).select_related("product", "seller"),
    seller,
  )
  return [
    order for order in orders
    if not is_terminal_cancelled_order(order)
    and not order_departed_wb_assembly(order)
  ]


def supply_ready_orders(supply: Supply, seller: Seller) -> list[Order]:
  return [
    order for order in assembly_supply_orders(supply, seller)
    if order_can_send_to_delivery(order)
  ]


def refresh_supply_readiness(supply: Supply, *, seller: Seller | None = None) -> Supply:
  if supply.status not in (Supply.Status.FORMING, Supply.Status.READY):
    return supply
  seller = seller or supply.seller
  _detach_departed_orders_from_active_supply(supply, seller)
  orders = assembly_supply_orders(supply, seller)
  if not orders:
    return supply
  all_ready = all(order_can_send_to_delivery(order) for order in orders)
  new_status = Supply.Status.READY if all_ready else Supply.Status.FORMING
  if supply.status != new_status:
    supply.status = new_status
    supply.save(update_fields=["status", "updated_at"])
  return supply


def supply_can_deliver(supply: Supply, *, seller: Seller | None = None) -> bool:
  if supply.status not in (Supply.Status.FORMING, Supply.Status.READY):
    return False
  if not supply.wb_supply_id:
    return False
  seller = seller or supply.seller
  orders = assembly_supply_orders(supply, seller)
  return bool(orders) and all(order_can_send_to_delivery(order) for order in orders)


def supply_can_force_deliver(supply: Supply, *, seller: Seller | None = None) -> bool:
  """Есть собранные заказы, но поставку блокируют «призраки» или неготовые."""
  if supply.status not in (Supply.Status.FORMING, Supply.Status.READY):
    return False
  if not supply.wb_supply_id:
    return False
  seller = seller or supply.seller
  if supply_can_deliver(supply, seller=seller):
    return False
  return bool(supply_ready_orders(supply, seller))


@transaction.atomic
def send_supply_to_delivery(
  seller: Seller,
  supply_id: int,
  *,
  user=None,
  shipping_point_id: int | None = None,
  shipping_date: date | None = None,
  shipping_type: str = "selfShipping",
  force: bool = False,
) -> dict:
  supply = (
    Supply.objects.filter(pk=supply_id, seller=seller)
    .prefetch_related("orders__product", "orders__seller")
    .first()
  )
  if not supply:
    raise SupplyFlowError("Поставка не найдена", code="not_found")

  if seller_has_warehouse_config(seller):
    enabled = get_enabled_wb_warehouse_ids(seller)
    if supply.wb_warehouse_id is not None and int(supply.wb_warehouse_id) not in enabled:
      raise SupplyFlowError(
        "Поставка с выключенного или необслуживаемого склада — включите склад или работайте в ЛК WB.",
        code="warehouse_disabled",
      )

  refresh_supply_readiness(supply, seller=seller)
  ready_orders = supply_ready_orders(supply, seller)
  if force:
    if not ready_orders:
      raise SupplyFlowError(
        "Нет собранных заказов для принудительной передачи в доставку.",
        code="not_ready",
      )
  elif not supply_can_deliver(supply, seller=seller):
    reasons = [
      reason
      for order in assembly_supply_orders(supply, seller)
      if (reason := order_delivery_block_reason(order))
    ]
    raise SupplyFlowError(
      "Поставка не готова: " + (reasons[0] if reasons else "проверьте заказы"),
      code="not_ready",
    )

  client = _get_client(seller)
  supply_barcode_file = ""
  supply_barcode_value = ""
  supply_barcode_error = ""

  if supply.status in (Supply.Status.FORMING, Supply.Status.READY):
    _prepare_supply_orders_for_deliver(seller, supply, user=user, force=force)
    try:
      if not shipping_point_id or not shipping_date:
        raise SupplyFlowError(
          "Укажите пункт отгрузки (СЦ/ПВЗ) и дату отгрузки — это обязательно для WB.",
          code="shipping_required",
        )
      already_delivered = _prepare_wb_supply_deliver(
        client,
        supply,
        shipping_point_id=shipping_point_id,
        shipping_date=shipping_date,
        shipping_type=shipping_type,
      )
      if not already_delivered:
        client.deliver_supply(supply.wb_supply_id)
    except WBApiError as exc:
      raise SupplyFlowError(_parse_deliver_error(exc), code="wb_deliver_failed") from exc
    supply_barcode_file, supply_barcode_value, supply_barcode_error = _fetch_supply_barcode_payload(
      client,
      supply.wb_supply_id,
    )
    supply.status = Supply.Status.CONFIRMED
    supply.supply_barcode_printed = bool(supply_barcode_file)
    supply.save(update_fields=["status", "supply_barcode_printed", "updated_at"])
  elif supply.status == Supply.Status.CONFIRMED:
    if not shipping_point_id or not shipping_date:
      raise SupplyFlowError(
        "Укажите пункт отгрузки (СЦ) и дату — CRM отправит их в WB перед печатью QR.",
        code="shipping_required",
      )
    _prepare_wb_supply_deliver(
      client,
      supply,
      shipping_point_id=shipping_point_id,
      shipping_date=shipping_date,
      shipping_type=shipping_type,
    )
    supply_barcode_file, supply_barcode_value, supply_barcode_error = _fetch_supply_barcode_payload(
      client,
      supply.wb_supply_id,
    )

  assembly_orders = ready_orders if force else assembly_supply_orders(supply, seller)
  primary_order = next(
    (order for order in assembly_orders if order_can_send_to_delivery(order)),
    None,
  ) or (assembly_orders[0] if assembly_orders else None)
  if primary_order is None:
    raise SupplyFlowError(
      "В поставке нет заказов для передачи в доставку.",
      code="not_ready",
    )
  order, stock_info = _finalize_supply_after_wb_deliver(
    supply,
    seller=seller,
    user=user,
    primary_order=primary_order,
  )
  last_result = _delivery_result(
    order,
    supply,
    stock_info,
    supply_barcode_file,
    supply_barcode_value,
    supply_barcode_error,
    user=user,
    seller=seller,
  )

  _schedule_billing_refresh_after_delivery(seller)
  return last_result


def send_supplies_to_delivery_bulk(
  seller: Seller,
  *,
  supply_ids: list[int] | None = None,
  user=None,
  shipping_point_id: int | None = None,
  shipping_date: date | None = None,
  shipping_type: str = "selfShipping",
) -> dict:
  qs = filter_supplies_for_assembly(
    Supply.objects.filter(
      seller=seller,
      status__in=(Supply.Status.FORMING, Supply.Status.READY),
    ),
    seller,
  ).prefetch_related("orders__product", "orders__seller")
  if supply_ids is not None:
    qs = qs.filter(pk__in=supply_ids)

  delivered = 0
  errors: list[dict] = []
  barcode_files: list[str] = []

  for supply in qs:
    refresh_supply_readiness(supply, seller=seller)
    if not supply_can_deliver(supply, seller=seller):
      continue
    try:
      result = send_supply_to_delivery(
        seller,
        supply.id,
        user=user,
        shipping_point_id=shipping_point_id,
        shipping_date=shipping_date,
        shipping_type=shipping_type,
      )
      delivered += 1
      if result.get("supply_barcode_file"):
        barcode_files.append(result["supply_barcode_file"])
    except SupplyFlowError as exc:
      errors.append({
        "supply_id": supply.id,
        "wb_supply_id": supply.wb_supply_id,
        "error": str(exc),
      })

  if delivered == 0 and errors:
    raise SupplyFlowError(
      f"Не удалось передать ни одной поставки. Пример: {errors[0]['error']}",
      code="batch_failed",
    )

  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.SUPPLY,
    message=f"Массовая передача в доставку: {delivered} поставок",
    details={"delivered": delivered, "errors": errors},
  )

  return {
    "delivered": delivered,
    "errors": errors,
    "supply_barcode_files": barcode_files,
  }


def fetch_supply_barcode(seller: Seller, supply_id: int) -> dict:
  supply = Supply.objects.filter(pk=supply_id, seller=seller).first()
  if not supply:
    raise SupplyFlowError("Поставка не найдена", code="not_found")
  if supply.status != Supply.Status.CONFIRMED:
    raise SupplyFlowError(
      "ШК поставки доступен только после передачи в доставку",
      code="not_confirmed",
    )
  if not supply.wb_supply_id:
    raise SupplyFlowError("У поставки нет ID WB", code="no_wb_id")

  client = _get_client(seller)
  supply_barcode_file, supply_barcode_value, last_error = _fetch_supply_barcode_payload(
    client,
    supply.wb_supply_id,
  )

  if not supply_barcode_file:
    raise SupplyFlowError(
      last_error or "WB не вернул изображение ШК поставки",
      code="empty_barcode",
    )

  supply.supply_barcode_printed = True
  supply.save(update_fields=["supply_barcode_printed", "updated_at"])

  return {
    "wb_supply_id": supply.wb_supply_id,
    "supply_barcode_file": supply_barcode_file,
    "supply_barcode": supply_barcode_value,
  }
