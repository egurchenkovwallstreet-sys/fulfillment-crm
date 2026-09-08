"""Приёмка по карточкам WB: факт в CRM, сверка с ЛК, выставление остатков FBS."""
from __future__ import annotations

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.accounts.tenant import fulfillment_for_staff_user
from apps.integrations.marketplace import WB, normalize_marketplace
from apps.integrations.models import AuditLog
from apps.orders.services.supply_flow import (
  new_stage_orders_queryset,
  order_counts_by_barcode_on_warehouse,
  picking_stage_orders_queryset,
)
from apps.sellers.models import Seller, SellerWarehouse
from apps.warehouse.models import (
  Product,
  ProductWarehouseStock,
  StockOperation,
  WbFactIntakeLine,
  WbFactIntakeSession,
)
from apps.warehouse.services.catalog_fetch import (
  CatalogError,
  fetch_seller_catalog_items,
  normalize_barcode,
)
from apps.warehouse.services.cell_label import build_cell_label_data
from apps.warehouse.services.cells import create_cell_with_next_number, refresh_cell_occupied
from apps.warehouse.services.wb_stocks import (
  WBStockError,
  fetch_wb_stocks_for_warehouses,
  get_seller_warehouse,
  set_wb_stocks_absolute_batch,
)

SCAN_MODE_PIECE = "piece"
SCAN_MODE_SET = "set"
COLOR_OK = "green"
COLOR_DIFF = "yellow"
COLOR_MISSING = "red"


class WbFactIntakeError(Exception):
  pass


def _require_scanning(session: WbFactIntakeSession) -> WbFactIntakeSession:
  if session.status != WbFactIntakeSession.Status.SCANNING:
    raise WbFactIntakeError("Приёмка уже завершена")
  if session.wb_pushed_at:
    raise WbFactIntakeError("Остатки уже выставлены в ЛК WB — редактирование закрыто")
  return session


def _resolve_seller(*, company_name: str, seller_id: int | None, user) -> Seller:
  fulfillment = fulfillment_for_staff_user(user) if user else None
  if not fulfillment:
    raise WbFactIntakeError("Фулфилмент не определён")
  if seller_id:
    seller = Seller.objects.filter(pk=seller_id, is_active=True, fulfillment=fulfillment).first()
    if not seller:
      raise WbFactIntakeError("Селлер не найден")
    return seller
  name = (company_name or "").strip()
  if not name:
    raise WbFactIntakeError("Выберите клиента")
  seller = Seller.objects.filter(
    company_name__iexact=name,
    is_active=True,
    fulfillment=fulfillment,
  ).first()
  if not seller:
    raise WbFactIntakeError("Селлер не найден — выберите клиента из списка")
  return seller


def _serialize_line(line: WbFactIntakeLine, extra: dict | None = None) -> dict:
  data = {
    "id": line.id,
    "barcode": line.barcode,
    "wb_nm_id": line.wb_nm_id,
    "vendor_code": line.vendor_code,
    "title": line.title,
    "tech_size": line.tech_size,
    "wb_size": line.wb_size,
    "size_label": line.tech_size or line.wb_size or "—",
    "photo_url": line.photo_url,
    "color_label": line.color_label,
    "requires_marking": line.requires_marking,
    "wb_stock_snapshot": line.wb_stock_snapshot,
    "accepted": line.accepted,
    "fact_quantity": line.fact_quantity,
    "cell_number": line.cell_number,
    "product_id": line.product_id,
  }
  if extra:
    data.update(extra)
  return data


def serialize_session(
  session: WbFactIntakeSession,
  *,
  include_accepted: bool = True,
  include_report: bool = False,
) -> dict:
  warehouse = session.warehouse
  accepted_qs = session.lines.filter(accepted=True)
  payload = {
    "id": session.id,
    "status": session.status,
    "seller_id": session.seller_id,
    "seller_name": session.seller.company_name,
    "warehouse_id": warehouse.id,
    "warehouse_name": warehouse.name or f"Склад #{warehouse.wb_warehouse_id}",
    "wb_warehouse_id": warehouse.wb_warehouse_id,
    "marketplace": session.marketplace,
    "catalog_count": session.catalog_count,
    "accepted_count": session.accepted_count,
    "can_edit": (
      session.status == WbFactIntakeSession.Status.SCANNING and not session.wb_pushed_at
    ),
    "wb_pushed_at": session.wb_pushed_at.isoformat() if session.wb_pushed_at else None,
    "created_at": session.created_at.isoformat() if session.created_at else None,
    "completed_at": session.completed_at.isoformat() if session.completed_at else None,
    "accepted": [],
    "report": None,
  }
  if include_accepted:
    payload["accepted"] = [
      _serialize_line(line)
      for line in accepted_qs.select_related("product").order_by("-scanned_at", "barcode")
    ]
  if include_report:
    payload["report"] = build_report(session)
  return payload


def _open_order_maps(session: WbFactIntakeSession) -> tuple[dict[str, int], dict[str, int]]:
  wb_wh = session.warehouse.wb_warehouse_id
  new_map = order_counts_by_barcode_on_warehouse(
    new_stage_orders_queryset(session.seller),
    wb_wh,
  )
  picking_map = order_counts_by_barcode_on_warehouse(
    picking_stage_orders_queryset(session.seller),
    wb_wh,
  )
  return new_map, picking_map


def _live_wb_stocks(session: WbFactIntakeSession, barcodes: list[str]) -> dict[str, int]:
  if not barcodes:
    return {}
  stock_map = fetch_wb_stocks_for_warehouses(session.seller, [session.warehouse], barcodes)
  live: dict[str, int] = {}
  for barcode in barcodes:
    by_wh = (stock_map.get(barcode) or {}).get("by_warehouse") or {}
    live[barcode] = int(by_wh.get(session.warehouse_id) or 0)
  return live


def _classify_row(
  *,
  accepted: bool,
  fact: int,
  expected: int,
) -> str | None:
  if accepted:
    return COLOR_OK if fact == expected else COLOR_DIFF
  if expected > 0:
    return COLOR_MISSING
  return None


def build_report(session: WbFactIntakeSession) -> dict:
  lines = list(session.lines.all())
  barcodes = [line.barcode for line in lines]
  new_map, picking_map = _open_order_maps(session)
  try:
    live_stocks = _live_wb_stocks(session, barcodes)
  except WBStockError:
    live_stocks = {line.barcode: line.wb_stock_snapshot for line in lines}

  groups = {COLOR_OK: [], COLOR_DIFF: [], COLOR_MISSING: []}
  for line in lines:
    wb_stock = int(live_stocks.get(line.barcode, line.wb_stock_snapshot) or 0)
    new_n = int(new_map.get(line.barcode) or 0)
    picking_n = int(picking_map.get(line.barcode) or 0)
    expected = wb_stock + new_n + picking_n
    color = _classify_row(
      accepted=line.accepted,
      fact=int(line.fact_quantity or 0),
      expected=expected,
    )
    if not color:
      continue
    fact = int(line.fact_quantity or 0) if line.accepted else 0
    wb_target = max(0, fact - new_n - picking_n) if line.accepted else 0
    groups[color].append(
      _serialize_line(
        line,
        {
          "wb_stock": wb_stock,
          "new_orders": new_n,
          "picking_orders": picking_n,
          "expected": expected,
          "wb_target": wb_target,
          "color": color,
        },
      )
    )

  return {
    "green": groups[COLOR_OK],
    "yellow": groups[COLOR_DIFF],
    "red": groups[COLOR_MISSING],
    "green_count": len(groups[COLOR_OK]),
    "yellow_count": len(groups[COLOR_DIFF]),
    "red_count": len(groups[COLOR_MISSING]),
  }


def _write_crm_fact(product: Product, warehouse: SellerWarehouse, fact: int, user, comment: str) -> None:
  fact = max(0, int(fact))
  before = int(product.quantity or 0)
  ProductWarehouseStock.objects.update_or_create(
    product=product,
    seller_warehouse=warehouse,
    defaults={"quantity": fact},
  )
  total = (
    ProductWarehouseStock.objects.filter(product=product).aggregate(s=Sum("quantity")).get("s")
  )
  product.quantity = int(total or 0)
  product.save(update_fields=["quantity", "updated_at"])
  refresh_cell_occupied(product.cell)
  delta = product.quantity - before
  if delta:
    StockOperation.objects.create(
      product=product,
      operation_type=(
        StockOperation.OperationType.INTAKE if delta > 0 else StockOperation.OperationType.ADJUSTMENT
      ),
      quantity=delta,
      performed_by=user if getattr(user, "is_authenticated", False) else None,
      comment=comment,
    )


def _ensure_product(session: WbFactIntakeSession, line: WbFactIntakeLine) -> tuple[Product, bool]:
  seller = session.seller
  existing = (
    Product.objects.filter(seller=seller, marketplace=WB, barcode=line.barcode)
    .select_related("cell")
    .first()
  )
  created = False
  if existing:
    product = existing
    cell = product.cell
  else:
    cell = create_cell_with_next_number(seller, WB)
    product = Product.objects.create(
      seller=seller,
      barcode=line.barcode,
      name=line.title,
      cell=cell,
      quantity=0,
      requires_marking=line.requires_marking,
      wb_nm_id=line.wb_nm_id,
      vendor_code=line.vendor_code,
      tech_size=line.tech_size,
      wb_size=line.wb_size,
      photo_url=line.photo_url,
      color_label=line.color_label,
      marketplace=WB,
    )
    created = True

  product.name = line.title or product.name
  product.requires_marking = line.requires_marking
  product.wb_nm_id = line.wb_nm_id
  product.vendor_code = line.vendor_code
  product.tech_size = line.tech_size
  product.wb_size = line.wb_size
  product.photo_url = line.photo_url or product.photo_url
  product.color_label = line.color_label
  product.save(
    update_fields=[
      "name",
      "requires_marking",
      "wb_nm_id",
      "vendor_code",
      "tech_size",
      "wb_size",
      "photo_url",
      "color_label",
      "updated_at",
    ]
  )
  refresh_cell_occupied(cell)
  line.product = product
  line.cell_number = cell.number
  return product, created


def create_session(
  *,
  company_name: str = "",
  seller_id: int | None = None,
  warehouse_id: int | None = None,
  user=None,
  marketplace: str = WB,
) -> WbFactIntakeSession:
  if normalize_marketplace(marketplace) != WB:
    raise WbFactIntakeError("Эта приёмка только для Wildberries")
  seller = _resolve_seller(company_name=company_name, seller_id=seller_id, user=user)
  if not seller.wb_api_token_encrypted:
    raise WbFactIntakeError("У селлера не задан токен WB")
  if not warehouse_id:
    raise WbFactIntakeError("Выберите склад FBS WB")
  try:
    warehouse = get_seller_warehouse(seller, int(warehouse_id))
  except (WBStockError, TypeError, ValueError) as exc:
    raise WbFactIntakeError(str(exc)) from exc

  try:
    items = fetch_seller_catalog_items(seller)
  except CatalogError as exc:
    raise WbFactIntakeError(str(exc)) from exc
  if not items:
    raise WbFactIntakeError("В ЛК WB нет карточек с баркодами")

  barcodes = [item.barcode for item in items]
  try:
    stock_map = fetch_wb_stocks_for_warehouses(seller, [warehouse], barcodes)
  except WBStockError as exc:
    raise WbFactIntakeError(str(exc)) from exc

  with transaction.atomic():
    session = WbFactIntakeSession.objects.create(
      seller=seller,
      warehouse=warehouse,
      created_by=user if getattr(user, "is_authenticated", False) else None,
      catalog_count=len(items),
    )
    bulk: list[WbFactIntakeLine] = []
    for item in items:
      by_wh = (stock_map.get(item.barcode) or {}).get("by_warehouse") or {}
      bulk.append(
        WbFactIntakeLine(
          session=session,
          barcode=item.barcode,
          wb_nm_id=item.wb_nm_id,
          vendor_code=item.vendor_code,
          title=item.title,
          tech_size=item.tech_size,
          wb_size=item.wb_size,
          photo_url=(item.photo_url or "")[:500],
          color_label=item.color_label,
          requires_marking=item.requires_marking,
          wb_stock_snapshot=int(by_wh.get(warehouse.id) or 0),
        )
      )
    WbFactIntakeLine.objects.bulk_create(bulk, batch_size=500)
  return session


def _apply_quantity(
  session: WbFactIntakeSession,
  line: WbFactIntakeLine,
  quantity: int,
  user,
) -> tuple[Product, bool]:
  if quantity < 0:
    raise WbFactIntakeError("Количество не может быть меньше 0")
  product, created = _ensure_product(session, line)
  line.accepted = True
  line.fact_quantity = quantity
  if line.scanned_at is None:
    line.scanned_at = timezone.now()
  line.save(
    update_fields=["accepted", "fact_quantity", "cell_number", "product", "scanned_at"],
  )
  _write_crm_fact(
    product,
    session.warehouse,
    quantity,
    user,
    comment=f"Приёмка карточек WB #{session.id}",
  )
  session.accepted_count = session.lines.filter(accepted=True).count()
  session.save(update_fields=["accepted_count"])
  return product, created


@transaction.atomic
def scan_barcode(
  session: WbFactIntakeSession,
  *,
  barcode: str,
  quantity: int = 0,
  scan_mode: str = SCAN_MODE_PIECE,
  user=None,
) -> dict:
  session = _require_scanning(session)
  code = normalize_barcode(barcode)
  if len(code) < 4:
    raise WbFactIntakeError("Отсканируйте баркод")
  line = session.lines.filter(barcode=code).first()
  if not line:
    raise WbFactIntakeError(f"Баркода {code} нет в ЛК WB")

  mode = (scan_mode or SCAN_MODE_PIECE).strip().lower()
  if mode == SCAN_MODE_SET:
    next_qty = int(quantity)
  else:
    next_qty = int(line.fact_quantity or 0) + 1
  product, created = _apply_quantity(session, line, next_qty, user)
  line.refresh_from_db()
  cell_label = build_cell_label_data(product) if created else None
  return {
    "session": serialize_session(session),
    "line": _serialize_line(line),
    "created_cell": created,
    "cell_label": cell_label,
  }


@transaction.atomic
def set_line_quantity(
  session: WbFactIntakeSession,
  *,
  barcode: str,
  quantity: int,
  user=None,
) -> dict:
  session = _require_scanning(session)
  code = normalize_barcode(barcode)
  line = session.lines.filter(barcode=code).first()
  if not line:
    raise WbFactIntakeError(f"Баркода {code} нет в ЛК WB")
  product, created = _apply_quantity(session, line, int(quantity), user)
  line.refresh_from_db()
  return {
    "session": serialize_session(session),
    "line": _serialize_line(line),
    "created_cell": created,
    "cell_label": build_cell_label_data(product) if created else None,
  }


def finish_session(session: WbFactIntakeSession, user=None) -> dict:
  session = _require_scanning(session)
  if not session.lines.filter(accepted=True).exists():
    raise WbFactIntakeError("Сначала примите хотя бы один баркод")

  report = build_report(session)
  push_items: list[tuple[str, int]] = []
  seen: set[str] = set()
  for color in (COLOR_OK, COLOR_DIFF, COLOR_MISSING):
    for row in report[color]:
      barcode = str(row.get("barcode") or "")
      if not barcode or barcode in seen:
        continue
      seen.add(barcode)
      push_items.append((barcode, int(row.get("wb_target") or 0)))

  try:
    pushed = set_wb_stocks_absolute_batch(session.seller, session.warehouse, push_items)
  except WBStockError as exc:
    raise WbFactIntakeError(str(exc)) from exc

  now = timezone.now()
  with transaction.atomic():
    session.wb_pushed_at = now
    session.completed_at = now
    session.status = WbFactIntakeSession.Status.COMPLETED
    session.save(update_fields=["wb_pushed_at", "completed_at", "status"])

    AuditLog.objects.create(
      user=user if getattr(user, "is_authenticated", False) else None,
      seller=session.seller,
      action_type=AuditLog.ActionType.INTAKE,
      message=(
        f"Приёмка карточек WB #{session.id}: выставлено {pushed} SKU на склад "
        f"{session.warehouse.name or session.warehouse.wb_warehouse_id}"
      ),
      details={
        "session_id": session.id,
        "warehouse_id": session.warehouse_id,
        "accepted": session.accepted_count,
        "green": report["green_count"],
        "yellow": report["yellow_count"],
        "red": report["red_count"],
        "pushed": pushed,
      },
    )
  payload = serialize_session(session, include_report=False)
  payload["report"] = report
  payload["pushed"] = pushed
  return payload


def delete_session(session: WbFactIntakeSession, user=None) -> dict:
  if session.wb_pushed_at:
    raise WbFactIntakeError("Нельзя удалить приёмку после выгрузки в ЛК WB")
  session_id = session.id
  session.delete()
  return {"deleted": True, "id": session_id}
