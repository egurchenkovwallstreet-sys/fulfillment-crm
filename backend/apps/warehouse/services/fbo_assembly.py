"""Сборка FBO (WB): короба, скан, Excel, списание CRM."""
from __future__ import annotations

from io import BytesIO

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.integrations.marketplace import WB
from apps.integrations.models import AuditLog
from apps.sellers.models import Seller
from apps.warehouse.models import (
  FboAssemblyBox,
  FboAssemblyLine,
  FboAssemblySession,
  Product,
  StockOperation,
)
from apps.warehouse.services.catalog_fetch import normalize_barcode
from apps.warehouse.services.cells import refresh_cell_occupied
from apps.warehouse.services.product_lookup import resolve_product_by_barcode

try:
  from openpyxl import Workbook
except ImportError:
  Workbook = None  # type: ignore


WRONG_SELLER_MESSAGE = "Товар не этого селлера или не внесён в CRM — проверьте"


class FboAssemblyError(Exception):
  def __init__(self, message: str, *, code: str | None = None):
    super().__init__(message)
    self.code = code


def _session_locked(session_id: int) -> FboAssemblySession:
  return FboAssemblySession.objects.select_for_update().select_related("seller").get(pk=session_id)


def _require_editable(session: FboAssemblySession) -> None:
  if session.status == FboAssemblySession.Status.COMPLETED:
    raise FboAssemblyError("Сборка FBO завершена")
  if session.status == FboAssemblySession.Status.PAUSED:
    raise FboAssemblyError("Сборка на паузе — нажмите «Продолжить»")


def resolve_seller_product(seller: Seller, barcode: str) -> Product | None:
  return resolve_product_by_barcode(
    seller,
    WB,
    barcode,
    select_cell=True,
    register_alias=False,
  )


def _deduct_one_if_positive(product: Product, *, user, box: FboAssemblyBox, barcode: str) -> bool:
  if product.quantity < 1:
    return False
  product.quantity -= 1
  product.save(update_fields=["quantity", "updated_at"])
  refresh_cell_occupied(product.cell)
  StockOperation.objects.create(
    product=product,
    operation_type=StockOperation.OperationType.SHIPMENT,
    quantity=1,
    performed_by=user,
    comment=(
      f"Сборка FBO: короб {box.box_number}, баркод {barcode}, "
      f"остаток {product.quantity} шт."
    ),
  )
  return True


def serialize_box_label(box: FboAssemblyBox) -> dict:
  session = box.session
  label_date = (box.closed_at or timezone.now()).date().isoformat()
  return {
    "seller_name": session.seller.company_name,
    "box_number": box.box_number,
    "date": label_date,
    "box_id": box.id,
  }


def serialize_line(line: FboAssemblyLine) -> dict:
  return {
    "id": line.id,
    "barcode": line.barcode,
    "quantity": line.quantity,
  }


def serialize_box(box: FboAssemblyBox, *, include_lines: bool = False) -> dict:
  lines = list(box.lines.all())
  data = {
    "id": box.id,
    "box_number": box.box_number,
    "status": box.status,
    "sort_order": box.sort_order,
    "closed_at": box.closed_at.isoformat() if box.closed_at else None,
    "total_units": sum(line.quantity for line in lines),
    "label": serialize_box_label(box),
  }
  if include_lines:
    data["lines"] = [serialize_line(line) for line in lines]
  return data


def serialize_session(session: FboAssemblySession, *, prefetch: bool = True) -> dict:
  if prefetch:
    boxes = list(
      session.boxes.prefetch_related("lines").order_by("sort_order", "id")
    )
  else:
    boxes = list(session.boxes.order_by("sort_order", "id"))

  open_box = next((b for b in boxes if b.status == FboAssemblyBox.Status.OPEN), None)
  total_units = 0
  box_payload = []
  for box in boxes:
    lines = list(box.lines.all()) if prefetch else []
    total_units += sum(line.quantity for line in lines)
    box_payload.append(serialize_box(box, include_lines=prefetch))

  return {
    "id": session.id,
    "seller_id": session.seller_id,
    "seller_name": session.seller.company_name,
    "status": session.status,
    "marketplace": session.marketplace,
    "created_at": session.created_at.isoformat(),
    "completed_at": session.completed_at.isoformat() if session.completed_at else None,
    "box_count": len(boxes),
    "total_units": total_units,
    "open_box_id": open_box.id if open_box else None,
    "open_box_number": open_box.box_number if open_box else "",
    "boxes": box_payload,
  }


@transaction.atomic
def create_session(*, seller: Seller, user) -> FboAssemblySession:
  if not seller.wb_enabled:
    raise FboAssemblyError("У клиента не подключён Wildberries")
  session = FboAssemblySession.objects.create(
    seller=seller,
    created_by=user,
    marketplace=WB,
    status=FboAssemblySession.Status.ACTIVE,
  )
  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.OTHER,
    message=f"Начата сборка FBO #{session.id}",
    details={"session_id": session.id},
  )
  return session


@transaction.atomic
def pause_session(session: FboAssemblySession) -> FboAssemblySession:
  session = _session_locked(session.pk)
  if session.status == FboAssemblySession.Status.COMPLETED:
    raise FboAssemblyError("Сборка уже завершена")
  session.status = FboAssemblySession.Status.PAUSED
  session.save(update_fields=["status"])
  return session


@transaction.atomic
def resume_session(session: FboAssemblySession) -> FboAssemblySession:
  session = _session_locked(session.pk)
  if session.status == FboAssemblySession.Status.COMPLETED:
    raise FboAssemblyError("Сборка уже завершена")
  session.status = FboAssemblySession.Status.ACTIVE
  session.save(update_fields=["status"])
  return session


@transaction.atomic
def complete_session(session: FboAssemblySession, *, user) -> FboAssemblySession:
  session = _session_locked(session.pk)
  if session.status == FboAssemblySession.Status.COMPLETED:
    raise FboAssemblyError("Сборка уже завершена")
  session.status = FboAssemblySession.Status.COMPLETED
  session.completed_at = timezone.now()
  session.save(update_fields=["status", "completed_at"])
  AuditLog.objects.create(
    user=user,
    seller=session.seller,
    action_type=AuditLog.ActionType.OTHER,
    message=f"Завершена сборка FBO #{session.id}",
    details={"session_id": session.id, "box_count": session.boxes.count()},
  )
  return session


@transaction.atomic
def create_box(session: FboAssemblySession, *, box_number: str) -> FboAssemblyBox:
  session = _session_locked(session.pk)
  _require_editable(session)
  number = (box_number or "").strip()
  if not number:
    raise FboAssemblyError("Введите номер короба")
  if session.boxes.filter(status=FboAssemblyBox.Status.OPEN).exists():
    raise FboAssemblyError("Сначала закройте текущий короб")
  max_order = session.boxes.aggregate(m=Max("sort_order"))["m"] or 0
  box = FboAssemblyBox.objects.create(
    session=session,
    box_number=number,
    status=FboAssemblyBox.Status.OPEN,
    sort_order=max_order + 1,
  )
  return box


@transaction.atomic
def close_box(session: FboAssemblySession, *, box_id: int) -> FboAssemblyBox:
  session = _session_locked(session.pk)
  _require_editable(session)
  box = session.boxes.select_for_update().filter(pk=box_id).first()
  if not box:
    raise FboAssemblyError("Короб не найден")
  if box.status == FboAssemblyBox.Status.CLOSED:
    raise FboAssemblyError("Короб уже закрыт")
  if not box.lines.exists():
    raise FboAssemblyError("Короб пуст — отсканируйте хотя бы один баркод")
  box.status = FboAssemblyBox.Status.CLOSED
  box.closed_at = timezone.now()
  box.save(update_fields=["status", "closed_at"])
  return box


@transaction.atomic
def scan_barcode(
  session: FboAssemblySession,
  *,
  box_id: int,
  barcode: str,
  user,
) -> tuple[FboAssemblyLine, bool]:
  """Скан в короб. Возвращает (строка, списано_ли_1_шт)."""
  session = _session_locked(session.pk)
  _require_editable(session)
  raw = (barcode or "").strip()
  if len(raw) < 4:
    raise FboAssemblyError("Слишком короткий баркод")

  box = session.boxes.select_for_update().filter(pk=box_id).first()
  if not box or box.session_id != session.id:
    raise FboAssemblyError("Короб не найден")
  if box.status != FboAssemblyBox.Status.OPEN:
    raise FboAssemblyError("Короб закрыт — создайте новый")

  product = resolve_seller_product(session.seller, raw)
  if not product:
    raise FboAssemblyError(WRONG_SELLER_MESSAGE, code="wrong_seller")

  code = normalize_barcode(product.barcode) or raw
  line, created = FboAssemblyLine.objects.get_or_create(
    box=box,
    barcode=code,
    defaults={"product": product, "quantity": 0},
  )
  if line.product_id is None and product:
    line.product = product
  line.quantity += 1
  line.save(update_fields=["product", "quantity"])

  deducted = _deduct_one_if_positive(product, user=user, box=box, barcode=code)
  return line, deducted


def build_excel_bytes(session: FboAssemblySession) -> bytes:
  if Workbook is None:
    raise FboAssemblyError("На сервере не установлен openpyxl для Excel")

  boxes = (
    session.boxes.prefetch_related("lines")
    .order_by("sort_order", "id")
  )
  wb = Workbook()
  ws = wb.active
  ws.title = "FBO"
  ws.append(["Баркод", "Количество", "", "", "Номер короба"])
  row_count = 0
  for box in boxes:
    for line in box.lines.order_by("id"):
      ws.append([line.barcode, line.quantity, "", "", box.box_number])
      row_count += 1
  ws.column_dimensions["A"].width = 24
  ws.column_dimensions["B"].width = 14
  ws.column_dimensions["E"].width = 18

  buffer = BytesIO()
  wb.save(buffer)
  return buffer.getvalue()
