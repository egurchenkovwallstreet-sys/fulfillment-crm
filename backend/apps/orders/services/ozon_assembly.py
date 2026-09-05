"""Сборка FBS Ozon: скан, ЧЗ, ship, этикетка PDF."""
from __future__ import annotations

import base64

from django.db import transaction
from django.utils import timezone

from apps.integrations.ozon_client import OzonApiError
from apps.orders.models import OzonPosting
from apps.orders.services.marking import validate_marking_code
from apps.orders.services.ozon_counts import OzonCountsError, ozon_client_for_seller
from apps.orders.services.ozon_postings import _match_product, serialize_ozon_posting
from apps.warehouse.models import Product, StockOperation


class OzonAssemblyError(Exception):
  def __init__(self, message: str, code: str = ""):
    super().__init__(message)
    self.code = code


def _seller_counts(seller) -> dict[str, int]:
  return {
    "new": OzonPosting.objects.filter(
      seller=seller, crm_stage=OzonPosting.CrmStage.NEW, ozon_status="awaiting_packaging",
    ).count(),
    "in_picking": OzonPosting.objects.filter(
      seller=seller, crm_stage=OzonPosting.CrmStage.IN_PICKING,
    ).count(),
    "in_delivery": OzonPosting.objects.filter(
      seller=seller, crm_stage=OzonPosting.CrmStage.IN_DELIVERY,
    ).count(),
  }


def _save_seller_counts(seller) -> dict[str, int]:
  counts = _seller_counts(seller)
  seller.ozon_count_new = counts["new"]
  seller.ozon_count_assembly = counts["in_picking"]
  seller.ozon_count_delivery = counts["in_delivery"]
  seller.save(
    update_fields=[
      "ozon_count_new",
      "ozon_count_assembly",
      "ozon_count_delivery",
      "updated_at",
    ]
  )
  return counts


def _marking_list(posting: OzonPosting) -> list[str]:
  codes = [str(item).strip() for item in (posting.marking_codes or []) if str(item).strip()]
  extra = (posting.marking_code or "").strip()
  if extra and extra not in codes:
    codes.append(extra)
  return codes


def _needed_marks(posting: OzonPosting) -> int:
  return max(1, posting.quantity or 1)


def _is_marking_complete(posting: OzonPosting) -> bool:
  if not posting.requires_marking:
    return True
  return len(_marking_list(posting)) >= _needed_marks(posting)


@transaction.atomic
def scan_ozon_barcode(seller, barcode: str) -> dict:
  code = (barcode or "").strip()
  if not code:
    raise OzonAssemblyError("Отсканируйте баркод")
  posting = (
    OzonPosting.objects.select_related("product", "product__cell")
    .filter(seller=seller, barcode=code, crm_stage=OzonPosting.CrmStage.NEW)
    .order_by("in_process_at")
    .first()
  )
  if not posting:
    posting = (
      OzonPosting.objects.select_related("product", "product__cell")
      .filter(seller=seller, offer_id=code, crm_stage=OzonPosting.CrmStage.NEW)
      .order_by("in_process_at")
      .first()
    )
  if not posting:
    posting = (
      OzonPosting.objects.select_related("product", "product__cell")
      .filter(seller=seller, product__barcode=code, crm_stage=OzonPosting.CrmStage.NEW)
      .order_by("in_process_at")
      .first()
    )
  if not posting:
    raise OzonAssemblyError("Отправление с этим баркодом не найдено во вкладке «Новые»")
  posting.crm_stage = OzonPosting.CrmStage.IN_PICKING
  posting.save(update_fields=["crm_stage", "updated_at"])
  counts = _save_seller_counts(seller)
  needs_marking = posting.requires_marking and not _is_marking_complete(posting)
  message = f"Отправление {posting.posting_number} на сборке"
  if needs_marking:
    message += ". Теперь отсканируйте Честный знак (DataMatrix на упаковке)"
  return {
    "success": True,
    "message": message,
    "action": "await_marking" if needs_marking else "scanned",
    "posting": serialize_ozon_posting(posting, seller=seller),
    "counts": counts,
  }


def _move_posting_to_picking(posting: OzonPosting) -> bool:
  if posting.crm_stage != OzonPosting.CrmStage.NEW:
    return False
  posting.crm_stage = OzonPosting.CrmStage.IN_PICKING
  posting.save(update_fields=["crm_stage", "updated_at"])
  return True


def bulk_move_ozon_to_assembly(seller, posting_ids: list[int]) -> dict:
  if not posting_ids:
    raise OzonAssemblyError("Выберите хотя бы одно отправление")
  moved: list[dict] = []
  skipped: list[dict] = []
  for raw_id in posting_ids:
    try:
      posting_id = int(raw_id)
    except (TypeError, ValueError):
      skipped.append({"posting_id": raw_id, "error": "Некорректный ID"})
      continue
    posting = (
      OzonPosting.objects.select_related("product", "product__cell")
      .filter(pk=posting_id, seller=seller)
      .first()
    )
    if not posting:
      skipped.append({"posting_id": posting_id, "error": "Отправление не найдено"})
      continue
    if posting.crm_stage != OzonPosting.CrmStage.NEW:
      skipped.append({
        "posting_id": posting_id,
        "error": "Уже не во вкладке «Новые»",
      })
      continue
    _move_posting_to_picking(posting)
    moved.append(serialize_ozon_posting(posting, seller=seller))
  if not moved:
    raise OzonAssemblyError(
      skipped[0]["error"] if len(skipped) == 1 else "Не удалось перевести выбранные отправления",
    )
  counts = _save_seller_counts(seller)
  message = f"На сборку: {len(moved)} отправлений"
  if skipped:
    message += f" (пропущено: {len(skipped)})"
  return {
    "success": True,
    "message": message,
    "moved_count": len(moved),
    "skipped": skipped,
    "postings": moved,
    "counts": counts,
  }


@transaction.atomic
def bind_ozon_marking(seller, posting_id: int, marking_code: str) -> dict:
  posting = (
    OzonPosting.objects.select_related("product", "product__cell")
    .filter(pk=posting_id, seller=seller)
    .first()
  )
  if not posting:
    raise OzonAssemblyError("Отправление не найдено")
  if posting.crm_stage != OzonPosting.CrmStage.IN_PICKING:
    raise OzonAssemblyError("Сначала отсканируйте отправление на сборке")
  if not posting.requires_marking:
    raise OzonAssemblyError("Для этого отправления Честный знак не нужен")

  normalized, validation_error = validate_marking_code(marking_code)
  if validation_error:
    raise OzonAssemblyError(validation_error, code="invalid_marking_code")

  duplicate = (
    OzonPosting.objects.filter(seller=seller, marking_code=normalized)
    .exclude(pk=posting.pk)
    .exists()
  )
  if not duplicate:
    for other in OzonPosting.objects.filter(seller=seller).exclude(pk=posting.pk).exclude(marking_codes=[]):
      if normalized in (other.marking_codes or []):
        duplicate = True
        break
  if duplicate:
    raise OzonAssemblyError(
      "Этот код ЧЗ уже привязан к другому отправлению. Возьмите другой экземпляр товара",
      code="duplicate_marking",
    )

  codes = _marking_list(posting)
  if normalized in codes:
    raise OzonAssemblyError("Этот код ЧЗ уже привязан к этому отправлению")
  needed = _needed_marks(posting)
  if len(codes) >= needed:
    raise OzonAssemblyError("Все коды Честного знака для этого отправления уже привязаны")

  codes.append(normalized)
  posting.marking_codes = codes
  posting.marking_code = normalized
  posting.marking_bound = len(codes) >= needed
  posting.save(update_fields=["marking_codes", "marking_code", "marking_bound", "updated_at"])

  left = needed - len(codes)
  if left > 0:
    message = f"ЧЗ принят ({len(codes)} из {needed}). Отсканируйте ещё {left} код(а)"
    action = "await_marking"
  else:
    message = f"Честный знак привязан к {posting.posting_number}. Можно нажать «В доставку»"
    action = "bound"
  return {
    "success": True,
    "message": message,
    "action": action,
    "posting": serialize_ozon_posting(posting, seller=seller),
    "counts": _seller_counts(seller),
  }


def _ship_packages(posting: OzonPosting) -> list[dict]:
  items = [item for item in (posting.products_json or []) if isinstance(item, dict)]
  if not items:
    items = [{
      "sku": posting.sku,
      "quantity": posting.quantity or 1,
      "offer_id": posting.offer_id,
    }]
  marks = _marking_list(posting)
  mark_index = 0
  products = []
  for item in items:
    sku = item.get("sku") or posting.sku
    if not sku:
      continue
    try:
      qty = max(1, int(item.get("quantity") or 1))
    except (TypeError, ValueError):
      qty = 1
    row: dict = {
      "product_id": int(sku),
      "quantity": qty,
    }
    if posting.requires_marking:
      exemplars = []
      for _ in range(qty):
        if mark_index < len(marks):
          exemplars.append({"mandatory_mark": marks[mark_index]})
          mark_index += 1
      if exemplars:
        row["exemplar_info"] = exemplars
    products.append(row)
  if not products:
    raise OzonAssemblyError("У отправления нет SKU Ozon — обновите данные")
  return [{"products": products}]


def _deduct_product_stock(product: Product | None, qty: int, posting: OzonPosting, user) -> dict | None:
  if not product or qty < 1:
    return None
  product.quantity = max(0, (product.quantity or 0) - qty)
  product.save(update_fields=["quantity", "updated_at"])
  StockOperation.objects.create(
    product=product,
    operation_type=StockOperation.OperationType.SHIPMENT,
    quantity=-qty,
    performed_by=user,
    comment=f"Ozon {posting.posting_number}",
  )
  return {
    "deducted": True,
    "already_deducted": False,
    "quantity": qty,
    "cell_number": product.cell.number if product.cell_id else "",
    "barcode": product.barcode,
  }


def ship_ozon_posting(seller, posting_id: int, *, user=None) -> dict:
  posting = (
    OzonPosting.objects.select_related("product", "product__cell")
    .filter(pk=posting_id, seller=seller)
    .first()
  )
  if not posting:
    raise OzonAssemblyError("Отправление не найдено")
  if posting.crm_stage != OzonPosting.CrmStage.IN_PICKING:
    raise OzonAssemblyError("Сначала отсканируйте отправление на сборке")
  if posting.requires_marking and not _is_marking_complete(posting):
    needed = _needed_marks(posting)
    have = len(_marking_list(posting))
    raise OzonAssemblyError(f"Сначала привяжите Честный знак ({have} из {needed})")

  packages = _ship_packages(posting)

  try:
    client = ozon_client_for_seller(seller)
    client.ship_posting(posting.posting_number, packages)
  except (OzonCountsError, OzonApiError) as exc:
    raise OzonAssemblyError(str(exc)) from exc

  posting.ozon_status = "awaiting_deliver"
  posting.crm_stage = OzonPosting.CrmStage.IN_DELIVERY
  posting.shipped_at = timezone.now()
  update_fields = ["ozon_status", "crm_stage", "shipped_at", "updated_at"]

  stock = None
  if not posting.stock_deducted:
    items = [item for item in (posting.products_json or []) if isinstance(item, dict)]
    if not items:
      items = [{"barcode": posting.barcode, "offer_id": posting.offer_id, "quantity": posting.quantity or 1}]
    deducted_total = 0
    last_stock = None
    seen_ids: set[int] = set()
    for item in items:
      try:
        qty = max(1, int(item.get("quantity") or 1))
      except (TypeError, ValueError):
        qty = 1
      product = posting.product if posting.product_id and not seen_ids else None
      if product:
        seen_ids.add(product.id)
      else:
        product = _match_product(
          seller,
          str(item.get("barcode") or ""),
          str(item.get("offer_id") or ""),
        )
        if product and product.id in seen_ids:
          product = None
        if product:
          seen_ids.add(product.id)
      last_stock = _deduct_product_stock(product, qty, posting, user) or last_stock
      deducted_total += qty
    posting.stock_deducted = True
    update_fields.append("stock_deducted")
    stock = last_stock or {"deducted": True, "quantity": deducted_total}

  posting.save(update_fields=update_fields)
  try:
    from apps.sellers.services.liter_billing import record_shipment_liter_charge_for_ozon_posting

    record_shipment_liter_charge_for_ozon_posting(posting, seller=seller)
  except Exception:
    import logging
    logging.getLogger(__name__).exception("liter shipment charge failed for ozon posting %s", posting.id)
  counts = _save_seller_counts(seller)
  return {
    "success": True,
    "message": (
      f"{posting.posting_number} передано к отгрузке. "
      "Через минуту нажмите «Этикетка» — Ozon готовит PDF."
    ),
    "posting": serialize_ozon_posting(posting, seller=seller),
    "counts": counts,
    "stock": stock,
  }


def bulk_ship_ozon_postings(seller, posting_ids: list[int], *, user=None) -> dict:
  if not posting_ids:
    raise OzonAssemblyError("Выберите хотя бы одно отправление")
  shipped: list[dict] = []
  errors: list[dict] = []
  for raw_id in posting_ids:
    try:
      posting_id = int(raw_id)
      result = ship_ozon_posting(seller, posting_id, user=user)
      shipped.append(result.get("posting") or {})
    except OzonAssemblyError as exc:
      errors.append({"posting_id": raw_id, "error": str(exc)})
  if not shipped:
    raise OzonAssemblyError(
      errors[0]["error"] if len(errors) == 1 else "Не удалось передать выбранные отправления",
    )
  counts = _save_seller_counts(seller)
  message = f"В доставку: {len(shipped)} отправлений"
  if errors:
    message += f" (ошибок: {len(errors)})"
  return {
    "success": True,
    "message": message,
    "shipped_count": len(shipped),
    "errors": errors,
    "counts": counts,
  }


def fetch_ozon_label(seller, posting_id: int) -> dict:
  posting = OzonPosting.objects.filter(pk=posting_id, seller=seller).first()
  if not posting:
    raise OzonAssemblyError("Отправление не найдено")
  if posting.crm_stage != OzonPosting.CrmStage.IN_DELIVERY:
    raise OzonAssemblyError("Этикетка доступна после «В доставку»")
  try:
    client = ozon_client_for_seller(seller)
    pdf = client.package_label([posting.posting_number])
  except (OzonCountsError, OzonApiError) as exc:
    code = getattr(exc, "code", "") or ""
    raise OzonAssemblyError(str(exc), code=code) from exc
  return {
    "success": True,
    "filename": f"{posting.posting_number}.pdf",
    "pdf_base64": base64.b64encode(pdf).decode("ascii"),
    "posting": serialize_ozon_posting(posting, seller=seller),
  }


def fetch_ozon_labels_bulk(seller, posting_ids: list[int]) -> dict:
  postings = list(
    OzonPosting.objects.filter(
      seller=seller,
      pk__in=posting_ids,
      crm_stage=OzonPosting.CrmStage.IN_DELIVERY,
    )
  )
  if not postings:
    raise OzonAssemblyError("Нет отправлений для печати этикеток")
  numbers = [item.posting_number for item in postings][:20]
  try:
    client = ozon_client_for_seller(seller)
    pdf = client.package_label(numbers)
  except (OzonCountsError, OzonApiError) as exc:
    code = getattr(exc, "code", "") or ""
    raise OzonAssemblyError(str(exc), code=code) from exc
  return {
    "success": True,
    "filename": "ozon-labels.pdf",
    "pdf_base64": base64.b64encode(pdf).decode("ascii"),
    "count": len(numbers),
  }
