"""Акт и ШК сдачи FBS Ozon (carriage create + approve)."""
from __future__ import annotations

import base64
from collections import defaultdict

from apps.integrations.ozon_client import OzonApiError
from apps.orders.models import OzonPosting
from apps.orders.services.ozon_counts import OzonCountsError, ozon_client_for_seller


class OzonActError(Exception):
  def __init__(self, message: str, code: str = ""):
    super().__init__(message)
    self.code = code


def _extract_carriage_id(payload: dict) -> int | None:
  if not isinstance(payload, dict):
    return None
  for key in ("carriage_id", "id"):
    value = payload.get(key)
    try:
      if value not in (None, ""):
        return int(value)
    except (TypeError, ValueError):
      continue
  result = payload.get("result")
  if isinstance(result, dict):
    return _extract_carriage_id(result)
  return None


def _find_existing_carriage(client, delivery_method_id: int) -> int | None:
  for status in ("new", "formed"):
    try:
      rows = client.carriage_delivery_list(status)
    except OzonApiError:
      continue
    for row in rows:
      method = row.get("delivery_method") or {}
      method_id = method.get("id") or row.get("delivery_method_id")
      try:
        if int(method_id or 0) != int(delivery_method_id):
          continue
      except (TypeError, ValueError):
        continue
      carriages = row.get("carriages") or []
      if not carriages and row.get("carriage_id"):
        carriages = [row]
      for carriage in carriages:
        if not isinstance(carriage, dict):
          continue
        cid = _extract_carriage_id(carriage)
        if cid:
          return cid
  return None


def _encode_optional(raw: bytes | None, *, as_pdf: bool) -> str:
  if not raw:
    return ""
  prefix = "data:application/pdf;base64," if as_pdf or raw[:4] == b"%PDF" else "data:image/png;base64,"
  if raw[:4] == b"%PDF":
    prefix = "data:application/pdf;base64,"
  return prefix + base64.b64encode(raw).decode("ascii")


def fetch_ozon_act_docs(seller, carriage_id: int) -> dict:
  try:
    client = ozon_client_for_seller(seller)
  except OzonCountsError as exc:
    raise OzonActError(str(exc)) from exc

  barcode = b""
  pdf = b""
  warning = ""
  try:
    barcode = client.act_get_barcode(int(carriage_id))
  except OzonApiError as exc:
    warning = str(exc)
  try:
    pdf = client.act_get_pdf(int(carriage_id))
  except OzonApiError as exc:
    if not warning:
      warning = str(exc)

  if not barcode and not pdf:
    raise OzonActError(
      warning or "Документы ещё готовятся. Подождите полминуты и нажмите «Повторить».",
      code="not_ready",
    )
  return {
    "success": True,
    "carriage_id": int(carriage_id),
    "barcode_file": _encode_optional(barcode, as_pdf=False),
    "pdf_base64": base64.b64encode(pdf).decode("ascii") if pdf else "",
    "filename": f"ozon-act-{carriage_id}.pdf",
    "warning": warning,
  }


def form_ozon_acts(seller) -> dict:
  postings = list(
    OzonPosting.objects.filter(
      seller=seller,
      crm_stage=OzonPosting.CrmStage.IN_DELIVERY,
    ).order_by("delivery_method_id", "id")
  )
  if not postings:
    raise OzonActError("Нет отправлений во вкладке «В доставке»")

  grouped: dict[int, list[OzonPosting]] = defaultdict(list)
  missing = 0
  for posting in postings:
    if not posting.delivery_method_id:
      missing += 1
      continue
    grouped[int(posting.delivery_method_id)].append(posting)
  if not grouped:
    raise OzonActError(
      "У отправлений нет метода доставки. Нажмите «Обновить из Ozon» и повторите."
    )

  try:
    client = ozon_client_for_seller(seller)
  except OzonCountsError as exc:
    raise OzonActError(str(exc)) from exc

  results = []
  for method_id, group in grouped.items():
    try:
      created = client.carriage_create(method_id, comment=f"CRM {seller.company_name}")
      carriage_id = _extract_carriage_id(created)
    except OzonApiError as exc:
      carriage_id = _find_existing_carriage(client, method_id)
      if not carriage_id:
        raise OzonActError(str(exc)) from exc
    if not carriage_id:
      carriage_id = _find_existing_carriage(client, method_id)
    if not carriage_id:
      raise OzonActError("Ozon не вернул ID отгрузки")

    try:
      client.carriage_approve(carriage_id)
    except OzonApiError as exc:
      text = str(exc).lower()
      if "already" not in text and "сформ" not in text and "formed" not in text:
        raise OzonActError(str(exc)) from exc

    OzonPosting.objects.filter(pk__in=[item.id for item in group]).update(carriage_id=carriage_id)

    docs = {"barcode_file": "", "pdf_base64": "", "warning": ""}
    try:
      docs = fetch_ozon_act_docs(seller, carriage_id)
    except OzonActError as exc:
      docs["warning"] = str(exc)

    results.append({
      "delivery_method_id": method_id,
      "carriage_id": carriage_id,
      "posting_count": len(group),
      "barcode_file": docs.get("barcode_file") or "",
      "pdf_base64": docs.get("pdf_base64") or "",
      "filename": docs.get("filename") or f"ozon-act-{carriage_id}.pdf",
      "warning": docs.get("warning") or "",
    })

  message = f"Сформировано отгрузок: {len(results)}"
  if missing:
    message += f". Без метода доставки пропущено {missing} шт. — обновите из Ozon"
  if any(item.get("warning") for item in results):
    message += ". ШК/акт ещё готовятся — нажмите «Повторить документы» через полминуты"
  return {
    "success": True,
    "message": message,
    "acts": results,
  }
