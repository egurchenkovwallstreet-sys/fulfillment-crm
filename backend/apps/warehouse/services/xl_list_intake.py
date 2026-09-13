"""Простой сбор баркодов в Excel: без ячеек, CRM, WB и XL-приёмки."""
from __future__ import annotations

from io import BytesIO

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.accounts.tenant import fulfillment_for_staff_user, get_user_fulfillment
from apps.integrations.models import AuditLog
from apps.warehouse.models import XlListLine, XlListSession

try:
  from openpyxl import Workbook
except ImportError:  # pragma: no cover
  Workbook = None


class XlListIntakeError(Exception):
  pass


def _normalize_barcode(value: str) -> str:
  barcode = (value or "").strip()
  if barcode.endswith("\r") or barcode.endswith("\n"):
    barcode = barcode.strip()
  return barcode


def _can_edit(session: XlListSession) -> bool:
  return session.status == XlListSession.Status.ACTIVE


def xl_list_sessions_for_user(user):
  fulfillment = get_user_fulfillment(user)
  if not fulfillment:
    return XlListSession.objects.none()
  return XlListSession.objects.filter(fulfillment=fulfillment)


def get_xl_list_session_for_user(user, session_id: int, *, prefetch_lines: bool = False):
  from django.shortcuts import get_object_or_404

  qs = xl_list_sessions_for_user(user)
  if prefetch_lines:
    qs = qs.prefetch_related("lines")
  return get_object_or_404(qs, pk=session_id)


def serialize_line(line: XlListLine) -> dict:
  return {
    "barcode": line.barcode,
    "quantity": line.quantity,
    "sort_order": line.sort_order,
  }


def serialize_session(session: XlListSession, *, last_line: XlListLine | None = None) -> dict:
  lines_obj = list(session.lines.order_by("sort_order"))
  lines = [serialize_line(line) for line in lines_obj]
  last = last_line or (lines_obj[-1] if lines_obj else None)
  return {
    "id": session.id,
    "title": session.title,
    "status": session.status,
    "unique_count": len(lines_obj),
    "total_quantity": sum(line.quantity for line in lines_obj),
    "last_barcode": last.barcode if last else "",
    "last_sort_order": last.sort_order if last else 0,
    "last_quantity": last.quantity if last else 0,
    "lines": lines,
    "created_at": session.created_at.isoformat() if session.created_at else None,
    "completed_at": session.completed_at.isoformat() if session.completed_at else None,
    "can_edit": _can_edit(session),
  }


@transaction.atomic
def create_session(*, title: str = "", user=None) -> XlListSession:
  fulfillment = fulfillment_for_staff_user(user) if user else None
  if not fulfillment:
    raise XlListIntakeError("Фулфилмент не определён")
  session = XlListSession.objects.create(
    title=(title or "").strip(),
    fulfillment=fulfillment,
    created_by=user,
  )
  AuditLog.objects.create(
    user=user,
    action_type=AuditLog.ActionType.INTAKE,
    message=f"XL-список #{session.id}: новый список баркодов",
    details={"session_id": session.id, "title": session.title},
  )
  return session


def _next_sort_order(session: XlListSession) -> int:
  current = session.lines.aggregate(max_order=Max("sort_order"))["max_order"]
  return (current or 0) + 1


@transaction.atomic
def scan_unit(session: XlListSession, barcode: str) -> tuple[XlListSession, XlListLine]:
  session = XlListSession.objects.select_for_update().get(pk=session.pk)
  if not _can_edit(session):
    raise XlListIntakeError("Список завершён")
  barcode = _normalize_barcode(barcode)
  if len(barcode) < 4:
    raise XlListIntakeError("Баркод слишком короткий")

  line = session.lines.filter(barcode=barcode).first()
  if line:
    line.quantity += 1
    line.save(update_fields=["quantity"])
  else:
    line = XlListLine.objects.create(
      session=session,
      barcode=barcode,
      quantity=1,
      sort_order=_next_sort_order(session),
    )
  return session, line


@transaction.atomic
def add_line(
  session: XlListSession,
  *,
  barcode: str,
  quantity: int,
) -> XlListSession:
  session = XlListSession.objects.select_for_update().get(pk=session.pk)
  if not _can_edit(session):
    raise XlListIntakeError("Список завершён")
  barcode = _normalize_barcode(barcode)
  if len(barcode) < 4:
    raise XlListIntakeError("Баркод слишком короткий")
  if quantity < 1:
    raise XlListIntakeError("Количество должно быть больше нуля")

  line = session.lines.filter(barcode=barcode).first()
  if line:
    line.quantity += quantity
    line.save(update_fields=["quantity"])
  else:
    XlListLine.objects.create(
      session=session,
      barcode=barcode,
      quantity=quantity,
      sort_order=_next_sort_order(session),
    )
  return session


@transaction.atomic
def update_line_quantity(session: XlListSession, *, barcode: str, quantity: int) -> XlListSession:
  session = XlListSession.objects.select_for_update().get(pk=session.pk)
  if not _can_edit(session):
    raise XlListIntakeError("Список завершён")
  barcode = _normalize_barcode(barcode)
  line = session.lines.filter(barcode=barcode).first()
  if not line:
    raise XlListIntakeError("Баркод не найден в списке")
  if quantity < 0:
    raise XlListIntakeError("Количество не может быть отрицательным")
  if quantity == 0:
    line.delete()
  else:
    line.quantity = quantity
    line.save(update_fields=["quantity"])
  return session


@transaction.atomic
def delete_line(session: XlListSession, *, barcode: str) -> XlListSession:
  session = XlListSession.objects.select_for_update().get(pk=session.pk)
  if not _can_edit(session):
    raise XlListIntakeError("Список завершён")
  barcode = _normalize_barcode(barcode)
  line = session.lines.filter(barcode=barcode).first()
  if not line:
    raise XlListIntakeError("Баркод не найден в списке")
  line.delete()
  return session


def build_excel_bytes(session: XlListSession) -> bytes:
  if Workbook is None:
    raise XlListIntakeError("На сервере не установлен openpyxl для Excel")
  if not session.lines.exists():
    raise XlListIntakeError("Список пуст")

  wb = Workbook()
  ws = wb.active
  ws.title = "Баркоды"
  ws.append(["Баркод", "Количество"])
  for line in session.lines.order_by("sort_order"):
    ws.append([line.barcode, line.quantity])
  ws.column_dimensions["A"].width = 24
  ws.column_dimensions["B"].width = 14

  buffer = BytesIO()
  wb.save(buffer)
  return buffer.getvalue()


@transaction.atomic
def complete_session(session: XlListSession, *, user=None) -> XlListSession:
  session = XlListSession.objects.select_for_update().get(pk=session.pk)
  if session.status == XlListSession.Status.COMPLETED:
    raise XlListIntakeError("Список уже завершён")
  if not session.lines.exists():
    raise XlListIntakeError("Список пуст")
  session.status = XlListSession.Status.COMPLETED
  session.completed_at = timezone.now()
  session.save(update_fields=["status", "completed_at"])
  AuditLog.objects.create(
    user=user,
    action_type=AuditLog.ActionType.INTAKE,
    message=f"XL-список #{session.id} завершён",
    details=serialize_session(session),
  )
  return session
