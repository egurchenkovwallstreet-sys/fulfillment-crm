"""Режим 2 сборки FBS: лента стикеров и связка баркод + стикер (+ ЧЗ)."""
from __future__ import annotations

import base64
import re

from django.db import transaction

from apps.integrations.models import AuditLog
from apps.integrations.marketplace import OZON, WB
from apps.orders.models import Order, OzonPosting, PickList, PickListItem
from apps.orders.services.assembly import (
  AssemblyError,
  _barcodes_match,
  _get_active_pick_list,
  _get_client,
  _is_marking_retry_order,
  _marking_error,
  _normalize_scan_value,
  _order_requires_marking,
  _reset_marking_for_retry,
  fetch_stickers_for_orders,
  format_sticker_number,
  sticker_scans_match,
)
from apps.orders.services.marking import MARKING_MIN_LEN, validate_marking_code
from apps.orders.services.ozon_assembly import OzonAssemblyError, bind_ozon_marking
from apps.orders.services.pick_list import PickListError, _cell_sort_key, _product_size_label, _product_wb_article
from apps.orders.services.wb_status import WB_SUPPLIER_ASSEMBLY
from apps.sellers.models import Seller
from apps.sellers.services.warehouse_filter import filter_orders_for_assembly
from apps.warehouse.models import Product


def _compact(value: str) -> str:
  return re.sub(r"\s+", "", (value or "").strip())


def _pick_list_orders_wb(pick_list: PickList, seller: Seller | None = None):
  qs = (
    Order.objects.filter(
      seller_id=pick_list.seller_id,
      pick_list=pick_list,
      assembly_hidden=False,
    )
    .exclude(status__in=[Order.Status.CANCELLED, Order.Status.SHIPPED])
    .select_related("product", "product__cell")
    .order_by("id")
  )
  return filter_orders_for_assembly(qs, seller or pick_list.seller)


def _pick_list_postings_ozon(pick_list: PickList):
  return (
    OzonPosting.objects.filter(
      seller_id=pick_list.seller_id,
      pick_list=pick_list,
    )
    .select_related("product", "product__cell")
    .order_by("in_process_at", "id")
  )


def _digits_equal(left: str, right: str) -> bool:
  if not left or not right:
    return False
  if left == right:
    return True
  if left.isdigit() and right.isdigit():
    return (left.lstrip("0") or "0") == (right.lstrip("0") or "0")
  return False


def _order_matches_sticker_wb(order: Order, scan: str) -> bool:
  scan_raw = (scan or "").strip()
  if not scan_raw:
    return False

  stored_scan = (order.sticker_scan_code or "").strip()
  if stored_scan and sticker_scans_match(stored_scan, scan_raw):
    return True

  scan_norm = _normalize_scan_value(scan_raw)
  if not scan_norm:
    return False

  if scan_norm.isdigit():
    try:
      if int(scan_norm) == order.wb_order_id:
        return True
    except (ValueError, OverflowError):
      pass
    if _digits_equal(scan_norm, str(order.wb_order_id)):
      return True

  part_a = _normalize_scan_value(order.sticker_part_a or "")
  part_b = _normalize_scan_value(order.sticker_part_b or "")

  if scan_norm == part_a or scan_norm == part_b:
    return True
  if part_a and _barcodes_match(part_a, scan_norm):
    return True
  if part_b and _barcodes_match(part_b, scan_norm):
    return True

  compact = _compact(scan_norm)
  if part_a and compact == _compact(part_a):
    return True
  if part_b and compact == _compact(part_b):
    return True

  if part_a and part_b:
    combined = _compact(part_a + part_b)
    if compact == combined:
      return True
    if scan_norm.isdigit() and len(scan_norm) == len(part_a) + len(part_b):
      head, tail = scan_norm[: len(part_a)], scan_norm[len(part_a) :]
      if (_barcodes_match(head, part_a) or _digits_equal(head, part_a)) and (
        _barcodes_match(tail, part_b) or _digits_equal(tail, part_b)
      ):
        return True
    for sep in ("/", "-", " ", "|"):
      label = f"{part_a}{sep}{part_b}"
      if compact == _compact(label):
        return True
    formatted = format_sticker_number(order)
    if formatted and compact == _compact(_normalize_scan_value(formatted)):
      return True
  return False


def _posting_matches_sticker_ozon(posting: OzonPosting, scan: str) -> bool:
  scan_value = (scan or "").strip()
  if not scan_value:
    return False
  if scan_value == posting.posting_number:
    return True
  if posting.ozon_order_id and scan_value.isdigit() and int(scan_value) == posting.ozon_order_id:
    return True
  return False


def _is_likely_marking(scan: str) -> bool:
  raw = (scan or "").strip()
  if len(raw) < MARKING_MIN_LEN:
    return False
  normalized, error = validate_marking_code(raw)
  if error and len(normalized) < MARKING_MIN_LEN:
    return False
  return True


def _pick_list_barcodes(pick_list: PickList) -> set[str]:
  return set(
    PickListItem.objects.filter(pick_list=pick_list).values_list("barcode", flat=True)
  )


def _scan_matches_pick_list_barcode(pick_list: PickList, scan: str) -> bool:
  scan_norm = _normalize_scan_value(scan)
  if not scan_norm:
    return False
  for barcode in _pick_list_barcodes(pick_list):
    if _barcodes_match(barcode or "", scan_norm):
      return True
  return False


def _orders_matching_barcode(orders: list[Order], barcode: str) -> list[Order]:
  barcode_norm = _normalize_scan_value(barcode)
  if not barcode_norm:
    return []
  return [
    order
    for order in orders
    if _barcodes_match(order.barcode or "", barcode_norm)
  ]


def _raise_sticker_barcode_mismatch(
  pick_list: PickList,
  *,
  barcode: str,
  sticker_scan: str,
  seller: Seller | None = None,
) -> None:
  """Стикер найден в листе, но не от заказа с этим баркодом."""
  orders = list(_pick_list_orders_wb(pick_list, seller))
  barcode_norm = _normalize_scan_value(barcode)
  sticker_orders = [order for order in orders if _order_matches_sticker_wb(order, sticker_scan)]
  barcode_orders = _orders_matching_barcode(orders, barcode_norm)

  if sticker_orders and barcode_orders:
    sticker_order = sticker_orders[0]
    if sticker_order.id not in {order.id for order in barcode_orders}:
      raise AssemblyError(
        f"Стикер заказа WB #{sticker_order.wb_order_id} "
        f"(баркод {sticker_order.barcode or '—'}) не совпадает с отсканированным баркодом "
        f"{barcode_norm}. Наклейте правильный стикер или отсканируйте верный баркод.",
        code="sticker_mismatch",
        order=sticker_order,
      )

  hint_order = barcode_orders[0] if len(barcode_orders) == 1 else (
    sticker_orders[0] if len(sticker_orders) == 1 else None
  )
  raise AssemblyError(
    "Стикер не совпадает с отсканированным баркодом. "
    "Отсканируйте QR-код с наклеенного стикера WB (буквенный код), "
    "не цифры partA/partB с этикетки.",
    code="sticker_mismatch",
    order=hint_order,
  )


def _info_label_payload(*, cell_number: str, tech_size: str, barcode: str, article: str, quantity: int) -> dict:
  return {
    "type": "info",
    "cell_number": cell_number or "—",
    "tech_size": tech_size or "—",
    "barcode": barcode or "—",
    "article": article or "—",
    "quantity": quantity,
  }


def get_wb_batch_ribbon(seller: Seller) -> dict:
  pick_list = _get_active_pick_list(seller)
  if not pick_list or not pick_list.items.exists():
    raise AssemblyError("Сначала сформируйте лист подбора", code="no_pick_list")

  orders = list(_pick_list_orders_wb(pick_list, seller))
  pending = [
    order
    for order in orders
    if order.status in (Order.Status.IN_PICKING, Order.Status.ASSEMBLED)
    or (
      order.status == Order.Status.LABEL_PRINTED
      and _order_requires_marking(order)
      and (order.marking_verify_status or "").strip() == "error"
    )
  ]
  if not pending:
    raise AssemblyError(
      "Нет стикеров для печати по выбранному складу. "
      "Нажмите «Сформировать лист подбора», затем снова «Печать ленты стикеров».",
      code="nothing_to_print",
    )

  missing_stickers = [order for order in pending if not order.has_sticker or not order.sticker_file]
  if missing_stickers:
    sample = missing_stickers[0]
    raise AssemblyError(
      f"Стикер для заказа WB #{sample.wb_order_id} ещё не загружен. "
      "Нажмите «Передать на сборку» или обновите заказы.",
      code="no_sticker",
    )

  missing_parts = [
    order
    for order in pending
    if not (order.sticker_part_a or "").strip()
    or not (order.sticker_part_b or "").strip()
    or not (order.sticker_scan_code or "").strip()
  ]
  if missing_parts:
    fetch_stickers_for_orders(seller, missing_parts)
    pending_ids = {order.id for order in pending}
    refreshed = {
      order.id: order
      for order in Order.objects.filter(id__in=pending_ids).only(
        "id",
        "sticker_part_a",
        "sticker_part_b",
        "sticker_scan_code",
      )
    }
    for index, order in enumerate(pending):
      fresh = refreshed.get(order.id)
      if not fresh:
        continue
      order.sticker_part_a = fresh.sticker_part_a
      order.sticker_part_b = fresh.sticker_part_b
      order.sticker_scan_code = fresh.sticker_scan_code
      pending[index] = order

  grouped: dict[str, dict] = {}
  for order in pending:
    bucket = grouped.setdefault(
      order.barcode,
      {
        "barcode": order.barcode,
        "cell_number": order.product.cell.number if order.product and order.product.cell_id else "—",
        "tech_size": (order.product.tech_size or order.product.wb_size or "—") if order.product else "—",
        "article": _product_wb_article(order.product) if order.product else "—",
        "quantity": 0,
        "orders": [],
      },
    )
    bucket["quantity"] += 1
    bucket["orders"].append({
      "id": order.id,
      "wb_order_id": order.wb_order_id,
      "barcode": order.barcode,
      "sticker_file": order.sticker_file,
      "sticker_part_a": order.sticker_part_a,
      "sticker_part_b": order.sticker_part_b,
      "sticker_scan_code": order.sticker_scan_code,
      "requires_marking": _order_requires_marking(order),
    })

  items: list[dict] = []
  for barcode in sorted(
    grouped.keys(),
    key=lambda code: _cell_sort_key(grouped[code]["cell_number"]),
  ):
    group = grouped[barcode]
    items.append(_info_label_payload(
      cell_number=group["cell_number"],
      tech_size=group["tech_size"],
      barcode=group["barcode"],
      article=group["article"],
      quantity=group["quantity"],
    ))
    for order in group["orders"]:
      items.append({
        "type": "sticker",
        "format": "png",
        "order_id": order["id"],
        "wb_order_id": order["wb_order_id"],
        "barcode": order["barcode"],
        "sticker_file": order["sticker_file"],
        "sticker_part_a": order["sticker_part_a"],
        "sticker_part_b": order["sticker_part_b"],
        "sticker_scan_code": order["sticker_scan_code"],
        "requires_marking": order["requires_marking"],
      })

  return {
    "pick_list_id": pick_list.id,
    "marketplace": WB,
    "items": items,
    "groups_count": len(grouped),
    "stickers_count": len(pending),
  }


def get_ozon_batch_ribbon(seller: Seller) -> dict:
  pick_list = (
    PickList.objects.filter(
      seller=seller,
      marketplace=OZON,
      is_completed=False,
    )
    .prefetch_related("items__cell", "items__product")
    .order_by("-created_at")
    .first()
  )
  if not pick_list or not pick_list.items.exists():
    raise AssemblyError("Сначала сформируйте лист подбора Ozon", code="no_pick_list")

  postings = list(_pick_list_postings_ozon(pick_list))
  pending = [
    posting
    for posting in postings
    if posting.crm_stage == OzonPosting.CrmStage.IN_PICKING
  ]
  if not pending:
    raise AssemblyError("Все отправления из листа уже собраны", code="nothing_to_print")

  grouped: dict[str, dict] = {}
  for posting in pending:
    barcode = (posting.barcode or posting.offer_id or "").strip() or "—"
    bucket = grouped.setdefault(
      barcode,
      {
        "barcode": barcode,
        "cell_number": posting.product.cell.number if posting.product and posting.product.cell_id else "—",
        "tech_size": (posting.product.tech_size or posting.product.wb_size or "—") if posting.product else "—",
        "article": (posting.offer_id or "").strip() or "—",
        "quantity": 0,
        "postings": [],
      },
    )
    bucket["quantity"] += max(1, posting.quantity or 1)
    bucket["postings"].append(posting)

  label_pdf_by_number: dict[str, str] = {}
  try:
    from apps.orders.services.ozon_assembly import ozon_client_for_seller

    client = ozon_client_for_seller(seller)
    numbers = [posting.posting_number for posting in pending][:20]
    pdf_bytes = client.package_label(numbers)
    label_pdf_by_number["__bulk__"] = base64.b64encode(pdf_bytes).decode("ascii")
  except Exception:
    label_pdf_by_number.clear()

  items: list[dict] = []
  for barcode in sorted(
    grouped.keys(),
    key=lambda code: _cell_sort_key(grouped[code]["cell_number"]),
  ):
    group = grouped[barcode]
    items.append(_info_label_payload(
      cell_number=group["cell_number"],
      tech_size=group["tech_size"],
      barcode=group["barcode"],
      article=group["article"],
      quantity=group["quantity"],
    ))
    for posting in group["postings"]:
      sticker_item = {
        "type": "sticker",
        "format": "posting_number",
        "posting_id": posting.id,
        "posting_number": posting.posting_number,
        "barcode": posting.barcode,
        "requires_marking": posting.requires_marking,
      }
      if label_pdf_by_number.get("__bulk__"):
        sticker_item["format"] = "pdf_bulk"
        sticker_item["pdf_base64"] = label_pdf_by_number["__bulk__"]
      items.append(sticker_item)

  return {
    "pick_list_id": pick_list.id,
    "marketplace": OZON,
    "items": items,
    "groups_count": len(grouped),
    "stickers_count": len(pending),
    "labels_from_ozon": bool(label_pdf_by_number),
  }


def _resolve_wb_order_for_bind(
  seller: Seller,
  pick_list: PickList,
  *,
  barcode: str,
  sticker_scan: str,
) -> Order:
  barcode = _normalize_scan_value(barcode)
  sticker_scan = (sticker_scan or "").strip()
  if not barcode or not sticker_scan:
    raise AssemblyError("Отсканируйте баркод и стикер заказа", code="incomplete_bind")

  if not _scan_matches_pick_list_barcode(pick_list, barcode):
    raise AssemblyError("Баркода нет в листе подбора!", code="not_in_pick_list")

  candidates = [
    order
    for order in _pick_list_orders_wb(pick_list).filter(
      status__in=[Order.Status.IN_PICKING, Order.Status.ASSEMBLED, Order.Status.LABEL_PRINTED],
    )
    if _barcodes_match(order.barcode or "", barcode)
  ]
  if not candidates:
    raise AssemblyError(
      "Заказ с этим баркодом не найден в текущей сборке",
      code="order_not_found",
    )

  matched = [order for order in candidates if _order_matches_sticker_wb(order, sticker_scan)]
  if not matched and candidates and not any((o.sticker_scan_code or "").strip() for o in candidates):
    fetch_stickers_for_orders(pick_list.seller, candidates)
    for order in candidates:
      order.refresh_from_db(fields=["sticker_part_a", "sticker_part_b", "sticker_scan_code"])
    matched = [order for order in candidates if _order_matches_sticker_wb(order, sticker_scan)]
  if not matched:
    _raise_sticker_barcode_mismatch(
      pick_list,
      barcode=barcode,
      sticker_scan=sticker_scan,
      seller=seller,
    )
  if len(matched) > 1:
    raise AssemblyError(
      "Стикер совпал с несколькими заказами — отсканируйте номер заказа WB",
      code="sticker_ambiguous",
    )
  order = matched[0]

  if _is_marking_retry_order(order):
    if not _order_requires_marking(order):
      raise AssemblyError(
        "Заказ с ошибкой ЧЗ не требует маркировки — обратитесь к администратору",
        code="marking_retry_invalid",
        order=order,
      )
    _reset_marking_for_retry(order, seller)

  if order.status == Order.Status.LABEL_PRINTED and not _is_marking_retry_order(order):
    raise AssemblyError(
      f"Заказ WB #{order.wb_order_id} уже собран",
      code="already_bound",
      order=order,
    )

  if not order.has_sticker or not order.sticker_file:
    raise AssemblyError(
      f"Стикер для заказа WB #{order.wb_order_id} не загружен",
      code="no_sticker",
      order=order,
    )

  return order


def _bind_marking_without_print(seller: Seller, order: Order, marking_code: str, *, user=None) -> Order:
  wb_status = (order.wb_supplier_status or "").strip()
  if wb_status != WB_SUPPLIER_ASSEMBLY:
    raise _marking_error(
      f"Заказ WB #{order.wb_order_id} не на сборке в WB "
      f"(статус: {wb_status or 'new'}). "
      "Сначала отправьте заказ на сборку.",
      order,
      code="wb_not_confirm",
    )

  normalized, validation_error = validate_marking_code(marking_code)
  if validation_error:
    raise _marking_error(validation_error, order, code="invalid_marking_code")

  duplicate = (
    Order.objects.filter(marking_code=normalized)
    .exclude(pk=order.pk)
    .exclude(marking_verify_status="error")
    .exists()
  )
  if duplicate:
    raise _marking_error(
      "Этот код ЧЗ уже использован для другого заказа в CRM. "
      "Возьмите другой экземпляр товара",
      order,
      code="duplicate_marking",
    )

  client = _get_client(seller)
  from apps.integrations.wb_client import WBApiError
  from apps.orders.services.marking import parse_wb_marking_error

  try:
    client.bind_order_sgtin(order.wb_order_id, [normalized])
  except WBApiError as exc:
    raise _marking_error(parse_wb_marking_error(exc), order, code="wb_bind_failed") from exc

  order.marking_code = normalized
  order.marking_bound = False
  order.marking_verify_status = "pending"
  order.marking_verify_error = ""
  order.status = Order.Status.LABEL_PRINTED
  order.save(
    update_fields=[
      "marking_code",
      "marking_bound",
      "marking_verify_status",
      "marking_verify_error",
      "status",
      "updated_at",
    ]
  )

  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.MARKING,
    message=f"ЧЗ (лента) отправлен в WB — заказ #{order.wb_order_id}",
    details={"order_id": order.id, "barcode": order.barcode},
  )
  return order


@transaction.atomic
def bind_wb_batch_scan(
  seller: Seller,
  *,
  scan: str = "",
  barcode: str = "",
  sticker_scan: str = "",
  marking_code: str = "",
  user=None,
) -> dict:
  pick_list = _get_active_pick_list(seller)
  if not pick_list:
    raise AssemblyError("Активный лист подбора не найден", code="no_pick_list")

  state = {
    "barcode": _normalize_scan_value(barcode),
    "sticker_scan": (sticker_scan or "").strip(),
    "marking_code": (marking_code or "").strip(),
  }

  scan_value = (scan or "").strip()
  kind = ""
  if scan_value:
    kind = classify_wb_batch_scan(seller, scan_value, partial=state)
    if kind == "barcode":
      scan_barcode = _normalize_scan_value(scan_value)
      if state["barcode"] and not _barcodes_match(state["barcode"], scan_barcode):
        raise AssemblyError(
          "Уже отсканирован другой баркод. Начните связку заново.",
          code="barcode_conflict",
        )
      state["barcode"] = scan_barcode
    elif kind == "sticker":
      if state["sticker_scan"] and not _same_sticker_scan(state["sticker_scan"], scan_value, seller, pick_list):
        raise AssemblyError(
          "Уже отсканирован другой стикер. Начните связку заново.",
          code="sticker_conflict",
        )
      state["sticker_scan"] = scan_value
    elif kind == "marking":
      normalized, validation_error = validate_marking_code(scan_value)
      if validation_error:
        raise AssemblyError(validation_error, code="invalid_marking_code")
      state["marking_code"] = normalized
    else:
      raise AssemblyError("Не удалось определить тип скана", code="unknown_scan")

  requires_marking = False
  if state["barcode"] and state["sticker_scan"]:
    order = _resolve_wb_order_for_bind(
      seller,
      pick_list,
      barcode=state["barcode"],
      sticker_scan=state["sticker_scan"],
    )
    requires_marking = _order_requires_marking(order)
  else:
    return {
      "complete": False,
      "requires_marking": _marking_required_for_batch_state(seller, pick_list, state),
      **state,
      "scan_kind": kind,
    }

  if requires_marking:
    if not state["marking_code"]:
      return {
        "complete": False,
        "requires_marking": True,
        "order_id": order.id,
        "wb_order_id": order.wb_order_id,
        **state,
      }
    order = _bind_marking_without_print(seller, order, state["marking_code"], user=user)
    message = (
      f"Связка завершена: заказ WB #{order.wb_order_id}. "
      "ЧЗ отправлен в WB на проверку."
    )
  else:
    order.status = Order.Status.LABEL_PRINTED
    order.save(update_fields=["status", "updated_at"])
    AuditLog.objects.create(
      user=user,
      seller=seller,
      action_type=AuditLog.ActionType.LABEL_PRINT,
      message=f"Связка (лента) — заказ WB #{order.wb_order_id}",
      details={"order_id": order.id, "barcode": order.barcode},
    )
    message = f"Связка завершена: заказ WB #{order.wb_order_id}."

  return {
    "complete": True,
    "requires_marking": requires_marking,
    "message": message,
    "order_id": order.id,
    "wb_order_id": order.wb_order_id,
    "barcode": "",
    "sticker_scan": "",
    "marking_code": "",
  }


def _same_sticker_scan(previous: str, new_value: str, seller: Seller, pick_list: PickList) -> bool:
  for order in _pick_list_orders_wb(pick_list):
    if _order_matches_sticker_wb(order, previous) and _order_matches_sticker_wb(order, new_value):
      return True
  return _compact(previous) == _compact(new_value)


def _marking_required_for_batch_state(seller: Seller, pick_list: PickList, state: dict) -> bool:
  if state.get("marking_code"):
    return True
  barcode = _normalize_scan_value(state.get("barcode") or "")
  if not barcode:
    return False
  for order in _pick_list_orders_wb(pick_list):
    if _barcodes_match(order.barcode or "", barcode):
      return _order_requires_marking(order)
    if barcode.isdigit() and order.wb_order_id == int(barcode):
      return _order_requires_marking(order)
  return False


def classify_wb_batch_scan(seller: Seller, scan: str, *, partial: dict | None = None) -> str:
  scan_value = (scan or "").strip()
  if not scan_value:
    raise AssemblyError("Пустой скан", code="empty_scan")

  pick_list = _get_active_pick_list(seller)
  if not pick_list:
    raise AssemblyError("Активный лист подбора не найден", code="no_pick_list")

  partial = partial or {}
  orders = list(_pick_list_orders_wb(pick_list))
  if orders and not any((order.sticker_scan_code or "").strip() for order in orders):
    fetch_stickers_for_orders(seller, orders)
    orders = list(_pick_list_orders_wb(pick_list))
  sticker_matches = [order for order in orders if _order_matches_sticker_wb(order, scan_value)]
  barcode_matches = _scan_matches_pick_list_barcode(pick_list, scan_value)

  partial_barcode = _normalize_scan_value(partial.get("barcode") or "")
  if partial_barcode and not partial.get("sticker_scan"):
    scoped = _orders_matching_barcode(orders, partial_barcode)
    if any(_order_matches_sticker_wb(order, scan_value) for order in scoped):
      return "sticker"
    sticker_orders = [order for order in orders if _order_matches_sticker_wb(order, scan_value)]
    if sticker_orders and scoped:
      wrong = sticker_orders[0]
      raise AssemblyError(
        f"Стикер заказа WB #{wrong.wb_order_id} "
        f"(баркод {wrong.barcode or '—'}) не совпадает с отсканированным баркодом "
        f"{partial_barcode}. Наклейте правильный стикер или отсканируйте верный баркод.",
        code="sticker_mismatch",
        order=wrong,
      )

  if partial.get("sticker_scan") and not partial_barcode and barcode_matches:
    return "barcode"

  if sticker_matches and not barcode_matches:
    return "sticker"
  if barcode_matches and not sticker_matches:
    return "barcode"
  if sticker_matches and barcode_matches:
    if partial_barcode and partial.get("sticker_scan"):
      return "marking" if _is_likely_marking(scan_value) else "barcode"
    if partial_barcode:
      return "sticker"
    if partial.get("sticker_scan"):
      return "barcode"
    if len(sticker_matches) == 1 and _barcodes_match(sticker_matches[0].barcode or "", scan_value):
      return "barcode"
    return "sticker"

  if _is_likely_marking(scan_value) and not sticker_matches:
    return "marking"

  if scan_value.isdigit():
    try:
      wb_id = int(scan_value)
    except (ValueError, OverflowError):
      wb_id = None
    if wb_id is not None:
      order = next((item for item in orders if item.wb_order_id == wb_id), None)
      if not order:
        order = next(
          (item for item in orders if _digits_equal(str(item.wb_order_id), scan_value)),
          None,
        )
      if order:
        return "sticker"

  if partial_barcode and not partial.get("sticker_scan"):
    scoped = _orders_matching_barcode(orders, partial_barcode)
    hint_order = scoped[0] if len(scoped) == 1 else None
    raise AssemblyError(
      "Стикер не найден в листе подбора — отсканируйте QR-код с наклеенного стикера WB "
      "(буквенный код, например !uKEtQZVx). Цифры partA/partB на этикетке не подходят.",
      code="sticker_mismatch",
      order=hint_order,
    )

  raise AssemblyError("Скан не найден в листе подбора", code="not_in_pick_list")


def _resolve_ozon_posting_for_bind(
  seller: Seller,
  pick_list: PickList,
  *,
  barcode: str,
  sticker_scan: str,
) -> OzonPosting:
  barcode = (barcode or "").strip()
  sticker_scan = (sticker_scan or "").strip()
  if not barcode or not sticker_scan:
    raise OzonAssemblyError("Отсканируйте баркод и стикер отправления", code="incomplete_bind")

  item_barcodes = _pick_list_barcodes(pick_list)
  if barcode not in item_barcodes:
    raise OzonAssemblyError("Баркода нет в листе подбора!", code="not_in_pick_list")

  postings = list(_pick_list_postings_ozon(pick_list))
  barcode_matches = [
    posting
    for posting in postings
    if (posting.barcode or "").strip() == barcode
    or (posting.offer_id or "").strip() == barcode
    or (posting.product and posting.product.barcode == barcode)
  ]
  if not barcode_matches:
    raise OzonAssemblyError("Отправление с этим баркодом не найдено в листе", code="order_not_found")

  matched = [posting for posting in barcode_matches if _posting_matches_sticker_ozon(posting, sticker_scan)]
  if not matched:
    sticker_matches = [
      posting for posting in postings if _posting_matches_sticker_ozon(posting, sticker_scan)
    ]
    if sticker_matches and barcode_matches:
      wrong = sticker_matches[0]
      raise OzonAssemblyError(
        f"Стикер отправления {wrong.posting_number} "
        f"(баркод {wrong.barcode or wrong.offer_id or '—'}) не совпадает с отсканированным баркодом "
        f"{barcode}. Наклейте правильный стикер или отсканируйте верный баркод.",
        code="sticker_mismatch",
      )
    raise OzonAssemblyError(
      "Стикер не совпадает с отсканированным баркодом",
      code="sticker_mismatch",
    )
  if len(matched) > 1:
    raise OzonAssemblyError(
      "Стикер совпал с несколькими отправлениями — уточните номер",
      code="sticker_ambiguous",
    )
  posting = matched[0]
  if posting.crm_stage != OzonPosting.CrmStage.IN_PICKING:
    raise OzonAssemblyError("Отправление уже собрано", code="already_bound")
  return posting


@transaction.atomic
def bind_ozon_batch_scan(
  seller: Seller,
  *,
  scan: str = "",
  barcode: str = "",
  sticker_scan: str = "",
  marking_code: str = "",
  user=None,
) -> dict:
  pick_list = (
    PickList.objects.filter(seller=seller, marketplace=OZON, is_completed=False)
    .order_by("-created_at")
    .first()
  )
  if not pick_list:
    raise OzonAssemblyError("Активный лист подбора Ozon не найден", code="no_pick_list")

  state = {
    "barcode": (barcode or "").strip(),
    "sticker_scan": (sticker_scan or "").strip(),
    "marking_code": (marking_code or "").strip(),
  }
  scan_value = (scan or "").strip()
  kind = ""
  if scan_value:
    kind = classify_ozon_batch_scan(seller, scan_value, partial=state)
    if kind == "barcode":
      if state["barcode"] and state["barcode"] != scan_value:
        raise OzonAssemblyError("Уже отсканирован другой баркод", code="barcode_conflict")
      state["barcode"] = scan_value
    elif kind == "sticker":
      state["sticker_scan"] = scan_value
    elif kind == "marking":
      normalized, validation_error = validate_marking_code(scan_value)
      if validation_error:
        raise OzonAssemblyError(validation_error, code="invalid_marking_code")
      state["marking_code"] = normalized

  if not (state["barcode"] and state["sticker_scan"]):
    return {
      "complete": False,
      "requires_marking": False,
      **state,
      "scan_kind": kind,
    }

  posting = _resolve_ozon_posting_for_bind(
    seller,
    pick_list,
    barcode=state["barcode"],
    sticker_scan=state["sticker_scan"],
  )
  requires_marking = posting.requires_marking

  if requires_marking:
    if not state["marking_code"]:
      return {
        "complete": False,
        "requires_marking": True,
        "posting_id": posting.id,
        "posting_number": posting.posting_number,
        **state,
      }
    result = bind_ozon_marking(seller, posting.id, state["marking_code"])
    message = result["message"]
  else:
    posting.marking_bound = True
    posting.save(update_fields=["marking_bound", "updated_at"])
    message = f"Связка завершена: {posting.posting_number}. Можно передать в доставку."

  return {
    "complete": True,
    "requires_marking": requires_marking,
    "message": message,
    "posting_id": posting.id,
    "posting_number": posting.posting_number,
    "barcode": "",
    "sticker_scan": "",
    "marking_code": "",
  }


def classify_ozon_batch_scan(seller: Seller, scan: str, *, partial: dict | None = None) -> str:
  scan_value = (scan or "").strip()
  if not scan_value:
    raise OzonAssemblyError("Пустой скан", code="empty_scan")

  pick_list = (
    PickList.objects.filter(seller=seller, marketplace=OZON, is_completed=False)
    .order_by("-created_at")
    .first()
  )
  if not pick_list:
    raise OzonAssemblyError("Активный лист подбора Ozon не найден", code="no_pick_list")

  partial = partial or {}
  barcodes = _pick_list_barcodes(pick_list)
  postings = list(_pick_list_postings_ozon(pick_list))

  if _is_likely_marking(scan_value):
    return "marking"

  sticker_matches = [posting for posting in postings if _posting_matches_sticker_ozon(posting, scan_value)]
  barcode_matches = scan_value in barcodes or any(
    (posting.barcode or "").strip() == scan_value
    or (posting.offer_id or "").strip() == scan_value
    for posting in postings
  )

  if sticker_matches and not barcode_matches:
    return "sticker"
  if barcode_matches and not sticker_matches:
    return "barcode"
  if sticker_matches and barcode_matches:
    if partial.get("barcode"):
      return "sticker"
    if partial.get("sticker_scan"):
      return "barcode"
    return "sticker"

  raise OzonAssemblyError("Скан не найден в листе подбора", code="not_in_pick_list")


@transaction.atomic
def generate_ozon_pick_list(seller: Seller, *, user=None) -> PickList:
  existing = (
    PickList.objects.filter(seller=seller, marketplace=OZON, is_completed=False)
    .prefetch_related("items__cell", "items__product")
    .first()
  )
  if existing and existing.items.exists():
    return existing

  postings = list(
    OzonPosting.objects.filter(
      seller=seller,
      crm_stage=OzonPosting.CrmStage.IN_PICKING,
      pick_list__isnull=True,
    ).select_related("product", "product__cell")
  )
  if not postings:
    raise PickListError("Нет отправлений на сборке для листа подбора Ozon")

  grouped: dict[tuple, dict] = {}
  for posting in postings:
    product = posting.product
    barcode = (posting.barcode or posting.offer_id or "").strip()
    if not barcode:
      continue
    if product and product.cell_id:
      key = (product.cell_id, product.id, barcode)
    else:
      key = (0, 0, barcode)
    bucket = grouped.setdefault(
      key,
      {
        "product": product,
        "cell": product.cell if product and product.cell_id else None,
        "barcode": barcode,
        "quantity": 0,
        "posting_ids": [],
      },
    )
    bucket["quantity"] += max(1, posting.quantity or 1)
    bucket["posting_ids"].append(posting.id)

  if not grouped:
    raise PickListError("Нет баркодов для листа подбора Ozon")

  pick_list = PickList.objects.create(seller=seller, marketplace=OZON)
  db_items: list[PickListItem] = []
  posting_ids: list[int] = []
  for data in sorted(
    grouped.values(),
    key=lambda entry: _cell_sort_key(str(entry["cell"].number) if entry["cell"] else "—"),
  ):
    db_items.append(
      PickListItem(
        pick_list=pick_list,
        cell=data["cell"],
        product=data["product"],
        barcode=data["barcode"],
        quantity=data["quantity"],
      )
    )
    posting_ids.extend(data["posting_ids"])

  PickListItem.objects.bulk_create(db_items)
  OzonPosting.objects.filter(id__in=posting_ids).update(pick_list=pick_list)
  return pick_list
