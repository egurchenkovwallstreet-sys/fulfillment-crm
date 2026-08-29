"""Приёмка в XL: поштучный скан без API, Excel, ячейки после подключения WB."""
from __future__ import annotations

from io import BytesIO

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.accounts.tenant import fulfillment_for_staff_user
from apps.integrations.marketplace import WB, normalize_marketplace
from apps.integrations.models import AuditLog
from apps.integrations.wb_crypto import encrypt_token
from apps.sellers.models import Seller
from apps.sellers.services.invite import ensure_seller_invite
from apps.sellers.services.sync_warehouses import WarehouseSyncError, sync_seller_warehouses
from apps.warehouse.models import Product, StockOperation, XlIntakeLine, XlIntakeSession
from apps.warehouse.services.catalog_fetch import CatalogError, fetch_seller_catalog_items
from apps.warehouse.services.cells import create_cell_with_next_number, refresh_cell_occupied

try:
  from openpyxl import Workbook
except ImportError:  # pragma: no cover
  Workbook = None


class XlIntakeError(Exception):
  pass


def _normalize_barcode(value: str) -> str:
  barcode = (value or "").strip()
  if barcode.endswith("\r") or barcode.endswith("\n"):
    barcode = barcode.strip()
  return barcode


def _can_scan(session: XlIntakeSession) -> bool:
  return session.status != XlIntakeSession.Status.COMPLETED


def serialize_line(line: XlIntakeLine) -> dict:
  return {
    "barcode": line.barcode,
    "quantity": line.quantity,
    "applied_quantity": line.applied_quantity,
    "sort_order": line.sort_order,
  }


def serialize_session(
  session: XlIntakeSession,
  *,
  last_line: XlIntakeLine | None = None,
) -> dict:
  lines_obj = list(session.lines.order_by("sort_order"))
  lines = [serialize_line(line) for line in lines_obj]
  unique_count = len(lines_obj)
  total_quantity = sum(line.quantity for line in lines_obj)
  last = last_line or getattr(session, "_last_line", None)
  if last is None and lines_obj:
    last = lines_obj[-1]
  return {
    "id": session.id,
    "status": session.status,
    "seller_id": session.seller_id,
    "seller_name": session.seller.company_name,
    "has_wb_token": bool(session.seller.wb_api_token_encrypted),
    "marketplace": session.marketplace or WB,
    "unique_count": unique_count,
    "total_quantity": total_quantity,
    "last_barcode": last.barcode if last else "",
    "last_sort_order": last.sort_order if last else 0,
    "last_quantity": last.quantity if last else 0,
    "lines": lines,
    "unmatched": session.unmatched or [],
    "warehouse_sync_warning": session.warehouse_sync_warning,
    "created_at": session.created_at.isoformat() if session.created_at else None,
    "saved_at": session.saved_at.isoformat() if session.saved_at else None,
    "applied_at": session.applied_at.isoformat() if session.applied_at else None,
    "completed_at": session.completed_at.isoformat() if session.completed_at else None,
    "can_scan": _can_scan(session),
  }


@transaction.atomic
def create_session(*, company_name: str, user=None, marketplace: str = WB) -> XlIntakeSession:
  name = (company_name or "").strip()
  if not name:
    raise XlIntakeError("Укажите название ИП / компании")
  mp = normalize_marketplace(marketplace)
  fulfillment = fulfillment_for_staff_user(user) if user else None
  if not fulfillment:
    raise XlIntakeError("Фулфилмент не определён")
  seller = Seller.objects.create(
    company_name=name,
    fulfillment=fulfillment,
    wb_enabled=mp == WB,
    ozon_enabled=mp != WB,
  )
  ensure_seller_invite(seller)
  session = XlIntakeSession.objects.create(seller=seller, created_by=user, marketplace=mp)
  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.INTAKE,
    message=f"XL-приёмка #{session.id}: создан клиент «{name}» без токена ({mp})",
    details={"session_id": session.id, "marketplace": mp},
  )
  return session


@transaction.atomic
def create_session_for_seller(*, seller: Seller, user=None, marketplace: str = WB) -> XlIntakeSession:
  mp = normalize_marketplace(marketplace)
  session = XlIntakeSession.objects.create(seller=seller, created_by=user, marketplace=mp)
  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.INTAKE,
    message=f"XL-приёмка #{session.id}: новая сессия для «{seller.company_name}»",
    details={"session_id": session.id},
  )
  return session


@transaction.atomic
def scan_unit(session: XlIntakeSession, barcode: str) -> XlIntakeSession:
  session = XlIntakeSession.objects.select_for_update().select_related("seller").get(pk=session.pk)
  if not _can_scan(session):
    raise XlIntakeError("Приёмка завершена — сканирование закрыто")

  barcode = _normalize_barcode(barcode)
  if len(barcode) < 4:
    raise XlIntakeError("Баркод слишком короткий")

  line = (
    XlIntakeLine.objects.select_for_update()
    .filter(session=session, barcode=barcode)
    .first()
  )
  if line:
    line.quantity += 1
    line.save(update_fields=["quantity"])
  else:
    max_order = (
      XlIntakeLine.objects.select_for_update()
      .filter(session=session)
      .aggregate(m=Max("sort_order"))
      .get("m")
      or 0
    )
    line = XlIntakeLine.objects.create(
      session=session,
      barcode=barcode,
      quantity=1,
      sort_order=max_order + 1,
    )

  session._last_line = line  # noqa: SLF001 — передаём в serialize через параметр
  return session


def last_scanned_line(session: XlIntakeSession) -> XlIntakeLine | None:
  return getattr(session, "_last_line", None) or session.lines.order_by("-sort_order").first()


@transaction.atomic
def update_line_quantity(session: XlIntakeSession, *, barcode: str, quantity: int) -> XlIntakeSession:
  session = XlIntakeSession.objects.select_for_update().select_related("seller").get(pk=session.pk)
  if not _can_scan(session):
    raise XlIntakeError("Приёмка завершена — редактирование закрыто")
  barcode = _normalize_barcode(barcode)
  if quantity < 0:
    raise XlIntakeError("Количество не может быть отрицательным")
  line = XlIntakeLine.objects.select_for_update().filter(session=session, barcode=barcode).first()
  if not line:
    raise XlIntakeError("Строка не найдена")
  line.quantity = quantity
  line.save(update_fields=["quantity"])
  session._last_line = line  # noqa: SLF001
  return session


@transaction.atomic
def delete_line(session: XlIntakeSession, *, barcode: str) -> XlIntakeSession:
  session = XlIntakeSession.objects.select_for_update().select_related("seller").get(pk=session.pk)
  if not _can_scan(session):
    raise XlIntakeError("Приёмка завершена — редактирование закрыто")
  barcode = _normalize_barcode(barcode)
  deleted, _ = XlIntakeLine.objects.filter(session=session, barcode=barcode).delete()
  if not deleted:
    raise XlIntakeError("Строка не найдена")
  return session


@transaction.atomic
def save_session(session: XlIntakeSession, *, user=None) -> XlIntakeSession:
  session = XlIntakeSession.objects.select_for_update().select_related("seller").get(pk=session.pk)
  if session.status == XlIntakeSession.Status.COMPLETED:
    raise XlIntakeError("Приёмка завершена")
  if not session.lines.exists():
    raise XlIntakeError("Нет отсканированных баркодов")
  session.saved_at = timezone.now()
  if session.status == XlIntakeSession.Status.SCANNING:
    session.status = XlIntakeSession.Status.SAVED
  session.save(update_fields=["status", "saved_at"])
  AuditLog.objects.create(
    user=user,
    seller=session.seller,
    action_type=AuditLog.ActionType.INTAKE,
    message=f"XL-приёмка #{session.id} сохранена (контрольная точка)",
    details=serialize_session(session),
  )
  return session


def build_excel_bytes(session: XlIntakeSession) -> bytes:
  if Workbook is None:
    raise XlIntakeError("На сервере не установлен openpyxl для Excel")
  if not session.lines.exists():
    raise XlIntakeError("Нет отсканированных баркодов")

  wb = Workbook()
  ws = wb.active
  ws.title = "Приёмка"
  ws.append(["Баркод", "Количество"])
  for line in session.lines.order_by("sort_order"):
    ws.append([line.barcode, line.quantity])
  ws.column_dimensions["A"].width = 24
  ws.column_dimensions["B"].width = 14

  buffer = BytesIO()
  wb.save(buffer)
  return buffer.getvalue()


def _apply_card_fields(product: Product, item) -> None:
  product.name = item.title or product.name
  product.requires_marking = item.requires_marking
  product.wb_nm_id = item.wb_nm_id
  product.vendor_code = item.vendor_code
  product.tech_size = item.tech_size
  product.wb_size = item.wb_size
  product.photo_url = item.photo_url or product.photo_url


@transaction.atomic
def apply_after_wb(
  session: XlIntakeSession,
  *,
  token: str = "",
  user=None,
) -> dict:
  session = XlIntakeSession.objects.select_for_update().select_related("seller").get(pk=session.pk)
  if session.status == XlIntakeSession.Status.COMPLETED:
    raise XlIntakeError("Приёмка завершена")
  if not session.lines.exists():
    raise XlIntakeError("Нет отсканированных баркодов")

  seller = session.seller
  token = (token or "").strip()
  if token:
    seller.wb_api_token_encrypted = encrypt_token(token)
    seller.save(update_fields=["wb_api_token_encrypted", "updated_at"])
  elif not seller.wb_api_token_encrypted:
    raise XlIntakeError("Вставьте персональный токен WB")

  warehouse_warning = ""
  try:
    sync_seller_warehouses(seller, user=user)
  except WarehouseSyncError as exc:
    warehouse_warning = str(exc)

  try:
    catalog_items = fetch_seller_catalog_items(seller)
  except CatalogError as exc:
    raise XlIntakeError(str(exc)) from exc
  if not catalog_items:
    raise XlIntakeError("На WB не найдено карточек с баркодами")

  qty_by_barcode = {
    line.barcode: line.quantity
    for line in session.lines.order_by("sort_order")
  }
  delta_by_barcode = {
    line.barcode: line.quantity - line.applied_quantity
    for line in session.lines.order_by("sort_order")
    if line.quantity > line.applied_quantity
  }
  scanned = set(qty_by_barcode)
  matched_items = [item for item in catalog_items if item.barcode in scanned]
  matched_barcodes = {item.barcode for item in matched_items}
  unmatched = [
    {"barcode": barcode, "quantity": qty_by_barcode[barcode]}
    for barcode in qty_by_barcode
    if barcode not in matched_barcodes
  ]

  if not delta_by_barcode:
    session.unmatched = unmatched
    session.warehouse_sync_warning = warehouse_warning[:500]
    session.save(update_fields=["unmatched", "warehouse_sync_warning"])
    return {
      **serialize_session(session),
      "created_products": 0,
      "updated_products": 0,
      "created_cells": [],
      "unmatched_count": len(unmatched),
      "matched_count": len(matched_items),
    }

  if not matched_items:
    session.unmatched = unmatched
    session.warehouse_sync_warning = warehouse_warning[:500]
    session.save(update_fields=["unmatched", "warehouse_sync_warning"])
    return {
      **serialize_session(session),
      "created_products": 0,
      "updated_products": 0,
      "created_cells": [],
      "unmatched_count": len(unmatched),
      "matched_count": 0,
    }

  created_products = 0
  updated_products = 0
  created_cells: list[str] = []

  with transaction.atomic():
    lines_by_barcode = {
      line.barcode: line
      for line in session.lines.select_for_update().order_by("sort_order")
    }
    for item in matched_items:
      delta = delta_by_barcode.get(item.barcode, 0)
      if delta <= 0:
        continue
      line = lines_by_barcode[item.barcode]
      product = (
        Product.objects.select_related("cell")
        .filter(seller=seller, barcode=item.barcode, marketplace=session.marketplace)
        .first()
      )
      if product:
        product.quantity += delta
        _apply_card_fields(product, item)
        product.save()
        updated_products += 1
      else:
        cell = create_cell_with_next_number(seller, session.marketplace)
        product = Product.objects.create(
          seller=seller,
          barcode=item.barcode,
          cell=cell,
          quantity=delta,
          marketplace=session.marketplace,
        )
        _apply_card_fields(product, item)
        product.save()
        refresh_cell_occupied(cell)
        created_products += 1
        created_cells.append(cell.number)

      StockOperation.objects.create(
        product=product,
        operation_type=StockOperation.OperationType.INTAKE,
        quantity=delta,
        performed_by=user,
        comment=f"XL-приёмка #{session.id}",
      )
      line.applied_quantity = line.quantity
      line.save(update_fields=["applied_quantity"])

    session.status = XlIntakeSession.Status.APPLIED
    session.applied_at = timezone.now()
    session.unmatched = unmatched
    session.warehouse_sync_warning = warehouse_warning[:500]
    session.save(
      update_fields=["status", "applied_at", "unmatched", "warehouse_sync_warning"],
    )

  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.INTAKE,
    message=(
      f"XL-приёмка #{session.id}: карточки WB, ячеек {created_products}, "
      f"не найдено в ЛК {len(unmatched)}"
    ),
    details={
      "session_id": session.id,
      "created_products": created_products,
      "updated_products": updated_products,
      "unmatched": unmatched,
    },
  )

  return {
    **serialize_session(session),
    "created_products": created_products,
    "updated_products": updated_products,
    "created_cells": created_cells,
    "unmatched_count": len(unmatched),
    "matched_count": len(matched_items),
  }


@transaction.atomic
def complete_session(session: XlIntakeSession, *, user=None) -> XlIntakeSession:
  session = XlIntakeSession.objects.select_for_update().select_related("seller").get(pk=session.pk)
  if session.status == XlIntakeSession.Status.COMPLETED:
    raise XlIntakeError("Приёмка уже завершена")
  if not session.lines.exists():
    raise XlIntakeError("Нет отсканированных баркодов")
  session.status = XlIntakeSession.Status.COMPLETED
  session.completed_at = timezone.now()
  session.save(update_fields=["status", "completed_at"])
  AuditLog.objects.create(
    user=user,
    seller=session.seller,
    action_type=AuditLog.ActionType.INTAKE,
    message=f"XL-приёмка #{session.id} завершена",
    details=serialize_session(session),
  )
  return session
