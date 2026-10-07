"""Журнал приёмок для кабинета селлера (только просмотр, без типов режимов)."""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Q

from apps.integrations.marketplace import WB as MARKETPLACE_WB
from apps.integrations.marketplace import normalize_marketplace
from apps.integrations.models import AuditLog
from apps.sellers.models import Seller
from apps.warehouse.models import Product, StockOperation, WbFactIntakeLine, WbFactIntakeSession
from apps.warehouse.services.wb_stocks import STOCK_MODE_INTAKE, STOCK_MODE_SET_ACTUAL


class SellerIntakeReceiptNotFound(Exception):
  pass


def _receipt_id_manual(audit_id: int) -> str:
  return f"manual-{audit_id}"


def _receipt_id_excel(audit_id: int) -> str:
  return f"excel-{audit_id}"


def _receipt_id_fact(session_id: int) -> str:
  return f"fact-{session_id}"


def _parse_receipt_id(receipt_id: str) -> tuple[str, int]:
  if "-" not in receipt_id:
    raise SellerIntakeReceiptNotFound("Неверный идентификатор приёмки")
  kind, raw = receipt_id.split("-", 1)
  try:
    pk = int(raw)
  except ValueError as exc:
    raise SellerIntakeReceiptNotFound("Неверный идентификатор приёмки") from exc
  if kind not in ("manual", "excel", "fact"):
    raise SellerIntakeReceiptNotFound("Неверный идентификатор приёмки")
  return kind, pk


def _product_snapshot(seller: Seller, barcode: str, marketplace: str) -> dict:
  product = (
    Product.objects.filter(seller=seller, barcode=barcode, marketplace=marketplace)
    .only("name", "tech_size", "wb_size", "photo_url")
    .first()
  )
  if not product:
    return {"product_name": "", "tech_size": "", "photo_url": ""}
  size = (product.tech_size or product.wb_size or "").strip()
  return {
    "product_name": (product.name or "").strip(),
    "tech_size": size,
    "photo_url": (product.photo_url or "").strip(),
  }


def _manual_receipts(seller: Seller, marketplace: str, *, limit: int) -> list[dict]:
  qs = (
    AuditLog.objects.filter(
      seller=seller,
      action_type=AuditLog.ActionType.INTAKE,
    )
    .filter(
      Q(details__stock_mode=STOCK_MODE_INTAKE)
      | Q(details__stock_mode=STOCK_MODE_SET_ACTUAL)
    )
    .exclude(message__icontains="Импорт остатков Excel")
    .order_by("-created_at")[:limit]
  )
  receipts: list[dict] = []
  for log in qs:
    details = log.details or {}
    mp = normalize_marketplace(details.get("marketplace") or MARKETPLACE_WB)
    if mp != normalize_marketplace(marketplace):
      continue
    qty = details.get("quantity")
    if qty is None:
      continue
    receipts.append({
      "id": _receipt_id_manual(log.id),
      "created_at": log.created_at.isoformat(),
    })
  return receipts


def _excel_receipts(seller: Seller, *, limit: int) -> list[dict]:
  qs = (
    AuditLog.objects.filter(
      seller=seller,
      action_type=AuditLog.ActionType.INTAKE,
      details__mode__in=["increment", "set_minus_new"],
    )
    .order_by("-created_at")[:limit]
  )
  return [
    {
      "id": _receipt_id_excel(log.id),
      "created_at": log.created_at.isoformat(),
    }
    for log in qs
  ]


def _fact_session_receipts(seller: Seller, *, limit: int) -> list[dict]:
  qs = (
    WbFactIntakeSession.objects.filter(
      seller=seller,
      status=WbFactIntakeSession.Status.COMPLETED,
    )
    .order_by("-completed_at", "-id")[:limit]
  )
  receipts: list[dict] = []
  for session in qs:
    ts = session.completed_at or session.created_at
    receipts.append({
      "id": _receipt_id_fact(session.id),
      "created_at": ts.isoformat() if ts else session.created_at.isoformat(),
    })
  return receipts


def list_seller_intake_receipts(
  seller: Seller,
  *,
  marketplace: str,
  limit: int = 200,
) -> list[dict]:
  mp = normalize_marketplace(marketplace)
  per_source = max(limit // 3, 50)
  combined: list[dict] = []
  combined.extend(_manual_receipts(seller, mp, limit=per_source))
  if mp == MARKETPLACE_WB:
    combined.extend(_excel_receipts(seller, limit=per_source))
    combined.extend(_fact_session_receipts(seller, limit=per_source))
  combined.sort(key=lambda item: item["created_at"], reverse=True)
  return combined[:limit]


def _manual_receipt_detail(seller: Seller, audit_id: int, marketplace: str) -> dict:
  log = AuditLog.objects.filter(
    pk=audit_id,
    seller=seller,
    action_type=AuditLog.ActionType.INTAKE,
  ).first()
  if not log:
    raise SellerIntakeReceiptNotFound("Приёмка не найдена")
  details = log.details or {}
  if details.get("stock_mode") not in (STOCK_MODE_INTAKE, STOCK_MODE_SET_ACTUAL):
    raise SellerIntakeReceiptNotFound("Приёмка не найдена")
  mp = normalize_marketplace(details.get("marketplace") or MARKETPLACE_WB)
  if mp != normalize_marketplace(marketplace):
    raise SellerIntakeReceiptNotFound("Приёмка не найдена")
  barcode = (details.get("barcode") or "").strip()
  qty = int(details.get("quantity") or 0)
  snap = _product_snapshot(seller, barcode, mp)
  return {
    "id": _receipt_id_manual(log.id),
    "created_at": log.created_at.isoformat(),
    "items": [
      {
        "barcode": barcode,
        "quantity": qty,
        **snap,
      },
    ],
  }


def _excel_receipt_detail(seller: Seller, audit_id: int) -> dict:
  log = AuditLog.objects.filter(
    pk=audit_id,
    seller=seller,
    action_type=AuditLog.ActionType.INTAKE,
  ).first()
  if not log:
    raise SellerIntakeReceiptNotFound("Приёмка не найдена")
  mode = (log.details or {}).get("mode")
  if mode not in ("increment", "set_minus_new"):
    raise SellerIntakeReceiptNotFound("Приёмка не найдена")

  ts = log.created_at
  comment_need = "установка из Excel" if mode == "set_minus_new" else "Импорт Excel"
  ops = (
    StockOperation.objects.filter(
      product__seller=seller,
      created_at__gte=ts - timedelta(minutes=15),
      created_at__lte=ts + timedelta(seconds=5),
      comment__icontains=comment_need,
    )
    .select_related("product")
    .order_by("id")
  )
  items: list[dict] = []
  for op in ops:
    product = op.product
    barcode = product.barcode
    qty = int(op.quantity or 0)
    if qty < 0:
      qty = abs(qty)
    items.append({
      "barcode": barcode,
      "quantity": qty,
      "product_name": (product.name or "").strip(),
      "tech_size": (product.tech_size or product.wb_size or "").strip(),
      "photo_url": (product.photo_url or "").strip(),
    })
  return {
    "id": _receipt_id_excel(log.id),
    "created_at": log.created_at.isoformat(),
    "items": items,
  }


def _fact_receipt_detail(seller: Seller, session_id: int) -> dict:
  session = (
    WbFactIntakeSession.objects.filter(
      pk=session_id,
      seller=seller,
      status=WbFactIntakeSession.Status.COMPLETED,
    )
    .first()
  )
  if not session:
    raise SellerIntakeReceiptNotFound("Приёмка не найдена")
  lines = (
    WbFactIntakeLine.objects.filter(session=session, accepted=True)
    .exclude(fact_quantity__isnull=True)
    .order_by("id")
  )
  items = [
    {
      "barcode": line.barcode,
      "quantity": int(line.fact_quantity or 0),
      "product_name": (line.title or "").strip(),
      "tech_size": (line.tech_size or line.wb_size or "").strip(),
      "photo_url": (line.photo_url or "").strip(),
    }
    for line in lines
  ]
  ts = session.completed_at or session.created_at
  return {
    "id": _receipt_id_fact(session.id),
    "created_at": ts.isoformat() if ts else "",
    "items": items,
  }


def get_seller_intake_receipt_detail(
  seller: Seller,
  receipt_id: str,
  *,
  marketplace: str,
) -> dict:
  kind, pk = _parse_receipt_id(receipt_id)
  if kind == "manual":
    return _manual_receipt_detail(seller, pk, marketplace)
  if kind == "excel":
    if normalize_marketplace(marketplace) != MARKETPLACE_WB:
      raise SellerIntakeReceiptNotFound("Приёмка не найдена")
    return _excel_receipt_detail(seller, pk)
  if kind == "fact":
    if normalize_marketplace(marketplace) != MARKETPLACE_WB:
      raise SellerIntakeReceiptNotFound("Приёмка не найдена")
    return _fact_receipt_detail(seller, pk)
  raise SellerIntakeReceiptNotFound("Приёмка не найдена")
