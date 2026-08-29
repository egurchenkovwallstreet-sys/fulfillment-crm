"""Приёмка нового селлера: ячейки по артикулу+цвету, остатки только в CRM."""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.accounts.tenant import fulfillment_for_staff_user
from apps.integrations.marketplace import OZON, WB, normalize_marketplace
from apps.integrations.models import AuditLog
from apps.integrations.ozon_client import OzonApiError
from apps.orders.services.ozon_counts import OzonCountsError, ozon_client_for_seller
from apps.sellers.models import Seller, SellerOzonWarehouse, SellerWarehouse
from apps.sellers.services.invite import ensure_seller_invite
from apps.warehouse.models import ArticleIntakeSession, Cell, Product, StockOperation
from apps.warehouse.services.catalog_fetch import CatalogError
from apps.warehouse.services.catalog_groups import (
  find_group_by_barcode,
  group_key_for_item,
  serialize_group_preview,
)
from apps.warehouse.services.catalog_fetch import normalize_barcode
from apps.warehouse.services.cells import _next_cell_number, refresh_cell_occupied
from apps.warehouse.services.wb_stocks import (
  WBStockError,
  fetch_wb_stock_for_barcode,
  get_seller_warehouse,
  push_wb_stock_increment,
  set_wb_stock_absolute,
)


class ArticleIntakeError(Exception):
  pass


PUSH_MODE_REPLACE = "replace"
PUSH_MODE_ADD = "add"


def _require_active(session: ArticleIntakeSession) -> ArticleIntakeSession:
  if session.status != ArticleIntakeSession.Status.ACTIVE:
    raise ArticleIntakeError("Приёмка завершена")
  return session


def _require_editable(session: ArticleIntakeSession) -> ArticleIntakeSession:
  session = _require_active(session)
  if session.marketplace_pushed_at:
    raise ArticleIntakeError(
      "Приёмка заблокирована после выгрузки на маркетплейс — редактирование невозможно",
    )
  return session


def _session_product_qs(session: ArticleIntakeSession):
  keys = session.confirmed_group_keys or []
  if not keys:
    return Product.objects.none()
  return Product.objects.filter(
    seller=session.seller,
    marketplace=session.marketplace,
    article_group_key__in=keys,
  ).select_related("cell")


def _recalc_session_totals(session: ArticleIntakeSession) -> None:
  total = 0
  for product in _session_product_qs(session).only("quantity"):
    total += int(product.quantity or 0)
  session.total_units = total
  session.save(update_fields=["total_units"])


def _delete_product_and_cell(product: Product) -> None:
  cell = product.cell
  product.delete()
  if cell_id := getattr(cell, "id", None):
    cell_obj = Cell.objects.filter(pk=cell_id).first()
    if cell_obj and not cell_obj.products.exists():
      cell_obj.delete()
    elif cell_obj:
      refresh_cell_occupied(cell_obj)


def _seller_has_marketplace_api(seller: Seller, marketplace: str) -> None:
  mp = normalize_marketplace(marketplace)
  if mp == OZON:
    if not (seller.ozon_client_id and seller.ozon_api_key_encrypted):
      raise ArticleIntakeError("У селлера не настроен API Ozon")
    return
  if not seller.wb_api_token_encrypted:
    raise ArticleIntakeError("У селлера не задан токен WB")


def serialize_session(session: ArticleIntakeSession) -> dict:
  seller = session.seller
  mp = session.marketplace
  products_qs = _session_product_qs(session)
  products_count = products_qs.count()
  products = [_serialize_product(item) for item in products_qs.order_by("article_group_key", "tech_size", "barcode")]
  pushed = bool(session.marketplace_pushed_at)
  can_edit = session.status == ArticleIntakeSession.Status.ACTIVE and not pushed
  return {
    "id": session.id,
    "status": session.status,
    "seller_id": seller.id,
    "seller_name": seller.company_name,
    "marketplace": mp,
    "scan_count": session.scan_count,
    "total_units": session.total_units,
    "confirmed_groups_count": len(session.confirmed_group_keys or []),
    "products_count": products_count,
    "active_group_key": session.active_group_key or "",
    "marketplace_pushed_at": session.marketplace_pushed_at.isoformat() if session.marketplace_pushed_at else None,
    "can_scan": can_edit,
    "can_edit": can_edit,
    "can_push": products_count > 0 and not pushed,
    "products": products,
    "created_at": session.created_at.isoformat() if session.created_at else None,
    "completed_at": session.completed_at.isoformat() if session.completed_at else None,
  }


@transaction.atomic
def create_session(
  *,
  company_name: str = "",
  seller_id: int | None = None,
  user=None,
  marketplace: str = WB,
) -> ArticleIntakeSession:
  mp = normalize_marketplace(marketplace)
  fulfillment = fulfillment_for_staff_user(user) if user else None
  if not fulfillment:
    raise ArticleIntakeError("Фулфилмент не определён")

  if seller_id:
    seller = Seller.objects.filter(pk=seller_id, is_active=True, fulfillment=fulfillment).first()
    if not seller:
      raise ArticleIntakeError("Селлер не найден")
  else:
    name = (company_name or "").strip()
    if not name:
      raise ArticleIntakeError("Укажите название ИП или выберите клиента")
    seller = Seller.objects.create(
      company_name=name,
      fulfillment=fulfillment,
      wb_enabled=mp == WB,
      ozon_enabled=mp == OZON,
    )
    ensure_seller_invite(seller)

  _seller_has_marketplace_api(seller, mp)
  session = ArticleIntakeSession.objects.create(
    seller=seller,
    marketplace=mp,
    created_by=user,
  )
  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.INTAKE,
    message=f"Приёмка по артикулам #{session.id}: «{seller.company_name}» ({mp})",
    details={"session_id": session.id},
  )
  return session


def _add_product_stock(product: Product, quantity: int, user, comment: str) -> Product:
  if quantity <= 0:
    raise ArticleIntakeError("Количество должно быть больше 0")
  product.quantity += quantity
  product.save(update_fields=["quantity", "updated_at"])
  StockOperation.objects.create(
    product=product,
    operation_type=StockOperation.OperationType.INTAKE,
    quantity=quantity,
    performed_by=user,
    comment=comment,
  )
  return product


def _serialize_product(product: Product) -> dict:
  return {
    "id": product.id,
    "barcode": product.barcode,
    "name": product.name,
    "quantity": product.quantity,
    "cell_number": product.cell.number if product.cell_id else "",
    "tech_size": product.tech_size,
    "color_label": product.color_label,
    "article_group_key": product.article_group_key,
  }


@transaction.atomic
def scan_barcode(
  session: ArticleIntakeSession,
  *,
  barcode: str,
  quantity: int = 0,
  scan_mode: str = "lookup",
  user=None,
) -> dict:
  session = _require_editable(
    ArticleIntakeSession.objects.select_for_update().select_related("seller").get(pk=session.pk)
  )
  seller = session.seller
  mp = session.marketplace
  barcode = normalize_barcode(barcode)
  if len(barcode) < 4:
    raise ArticleIntakeError("Баркод слишком короткий")

  mode = (scan_mode or "lookup").strip().lower()
  product = Product.objects.filter(seller=seller, marketplace=mp, barcode=barcode).select_related("cell").first()

  if product and (session.confirmed_group_keys or []) and product.article_group_key in (session.confirmed_group_keys or []):
    if mode == "increment":
      return increment_product(session, barcode=barcode, user=user)
    return {
      "action": "known",
      "product": _serialize_product(product),
      "session": serialize_session(session),
    }

  if product:
    if mode == "increment":
      raise ArticleIntakeError("Баркод уже в CRM, но не из этой приёмки — укажите количество вручную")
    if quantity <= 0:
      raise ArticleIntakeError("Укажите количество больше 0")
    product = _add_product_stock(
      product,
      quantity,
      user,
      f"Приёмка по артикулам: +{quantity} шт.",
    )
    session.scan_count += 1
    session.total_units += quantity
    session.save(update_fields=["scan_count", "total_units"])
    return {
      "action": "added",
      "product": _serialize_product(product),
      "quantity_added": quantity,
      "session": serialize_session(session),
    }

  try:
    anchor, group_items, meta = find_group_by_barcode(seller, mp, barcode)
  except CatalogError as exc:
    raise ArticleIntakeError(str(exc)) from exc

  group_key = str(meta.get("group_key") or group_key_for_item(mp, anchor))

  if group_key in (session.confirmed_group_keys or []):
    raise ArticleIntakeError("Группа уже создана — отсканируйте баркод для +1 или введите количество")

  if Product.objects.filter(seller=seller, marketplace=mp, article_group_key=group_key).exists():
    raise ArticleIntakeError("Группа артикул+цвет уже есть в CRM, но этот баркод не найден")

  existing_barcodes = set(
    Product.objects.filter(seller=seller, marketplace=mp).values_list("barcode", flat=True)
  )
  start_cell = int(_next_cell_number(seller, mp))
  cell_numbers: dict[str, str] = {}
  num = start_cell
  for item in group_items:
    if item.barcode in existing_barcodes:
      continue
    cell_numbers[item.barcode] = str(num)
    num += 1

  preview = serialize_group_preview(
    mp,
    anchor,
    group_items,
    scanned_barcode=barcode,
    scanned_quantity=0,
    cell_numbers=cell_numbers,
    existing_barcodes=existing_barcodes,
    article_label=str(meta.get("article_label") or anchor.vendor_code or anchor.wb_nm_id),
  )
  preview["next_cell_number"] = start_cell
  return {
    "action": "preview",
    "preview": preview,
    "session": serialize_session(session),
  }


@transaction.atomic
def confirm_group(
  session: ArticleIntakeSession,
  *,
  scanned_barcode: str,
  scanned_quantity: int,
  items: list[dict],
  user=None,
) -> dict:
  session = _require_editable(
    ArticleIntakeSession.objects.select_for_update().select_related("seller").get(pk=session.pk)
  )
  seller = session.seller
  mp = session.marketplace
  scanned_barcode = normalize_barcode(scanned_barcode)

  try:
    anchor, group_items, meta = find_group_by_barcode(seller, mp, scanned_barcode)
  except CatalogError as exc:
    raise ArticleIntakeError(str(exc)) from exc

  group_key = str(meta.get("group_key") or group_key_for_item(mp, anchor))
  if group_key in (session.confirmed_group_keys or []):
    raise ArticleIntakeError("Эта группа уже подтверждена")

  by_barcode = {item.barcode: item for item in group_items}
  excluded = {
    normalize_barcode(str(row.get("barcode") or ""))
    for row in items
    if row.get("excluded")
  }
  excluded.discard("")

  payload_by_barcode = {
    normalize_barcode(str(row.get("barcode") or "")): row
    for row in items
    if normalize_barcode(str(row.get("barcode") or ""))
  }

  active_items = [
    item
    for item in group_items
    if item.barcode not in excluded
  ]
  if not active_items:
    raise ArticleIntakeError("Нельзя удалить все ячейки — оставьте хотя бы один размер")

  if scanned_barcode in excluded:
    raise ArticleIntakeError("Нельзя исключить отсканированный баркод")

  created_cells: list[str] = []
  created_products = 0
  created_items: list[dict] = []

  for item in active_items:
    if Product.objects.filter(seller=seller, marketplace=mp, barcode=item.barcode).exists():
      raise ArticleIntakeError(f"Баркод {item.barcode} уже есть в CRM")

    row = payload_by_barcode.get(item.barcode) or {}
    cell_number = str(row.get("cell_number") or "").strip()
    if not cell_number:
      cell_number = _next_cell_number(seller, mp)

    cell, _ = Cell.objects.get_or_create(
      seller=seller,
      marketplace=mp,
      number=cell_number,
      defaults={"is_occupied": False},
    )
    product = Product.objects.create(
      seller=seller,
      marketplace=mp,
      barcode=item.barcode,
      name=item.title,
      cell=cell,
      quantity=0,
      requires_marking=item.requires_marking,
      wb_nm_id=item.wb_nm_id,
      vendor_code=item.vendor_code,
      tech_size=item.tech_size,
      wb_size=item.wb_size,
      photo_url=item.photo_url,
      color_label=item.color_label,
      article_group_key=group_key,
    )
    refresh_cell_occupied(cell)
    created_cells.append(cell_number)
    created_products += 1
    created_items.append(_serialize_product(product))

  keys = list(session.confirmed_group_keys or [])
  keys.append(group_key)
  session.confirmed_group_keys = keys
  session.active_group_key = group_key
  session.scan_count += 1
  session.save(update_fields=["confirmed_group_keys", "active_group_key", "scan_count"])

  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.INTAKE,
    message=(
      f"Приёмка по артикулам #{session.id}: группа {anchor.vendor_code or anchor.wb_nm_id} "
      f"({anchor.color_label or '—'}), {created_products} ячеек"
    ),
    details={
      "session_id": session.id,
      "group_key": group_key,
      "created_cells": created_cells,
      "excluded_barcodes": sorted(excluded),
    },
  )

  return {
    "group_key": group_key,
    "created_products": created_products,
    "created_cells": created_cells,
    "products": created_items,
    "session": serialize_session(session),
  }


@transaction.atomic
def increment_product(
  session: ArticleIntakeSession,
  *,
  barcode: str,
  user=None,
) -> dict:
  session = _require_editable(
    ArticleIntakeSession.objects.select_for_update().select_related("seller").get(pk=session.pk)
  )
  barcode = normalize_barcode(barcode)
  product = (
    _session_product_qs(session)
    .select_for_update()
    .filter(barcode=barcode)
    .select_related("cell")
    .first()
  )
  if not product:
    raise ArticleIntakeError("Баркод не найден в этой приёмке")
  product = _add_product_stock(product, 1, user, "Приёмка по артикулам: +1 шт. (скан)")
  session.scan_count += 1
  session.total_units += 1
  session.active_group_key = product.article_group_key or session.active_group_key
  session.save(update_fields=["scan_count", "total_units", "active_group_key"])
  return {
    "action": "incremented",
    "product": _serialize_product(product),
    "quantity_added": 1,
    "session": serialize_session(session),
  }


@transaction.atomic
def save_group_quantities(
  session: ArticleIntakeSession,
  *,
  group_key: str,
  items: list[dict],
  user=None,
) -> dict:
  session = _require_editable(
    ArticleIntakeSession.objects.select_for_update().select_related("seller").get(pk=session.pk)
  )
  group_key = (group_key or session.active_group_key or "").strip()
  if not group_key:
    raise ArticleIntakeError("Не выбрана группа артикул+цвет")
  if group_key not in (session.confirmed_group_keys or []):
    raise ArticleIntakeError("Группа не найдена в этой приёмке")

  payload = {
    normalize_barcode(str(row.get("barcode") or "")): int(row.get("quantity") or 0)
    for row in items
    if normalize_barcode(str(row.get("barcode") or ""))
  }
  updated = 0
  for product in _session_product_qs(session).select_for_update().filter(article_group_key=group_key):
    if product.barcode not in payload:
      continue
    new_qty = max(0, payload[product.barcode])
    old_qty = int(product.quantity or 0)
    if new_qty == old_qty:
      continue
    delta = new_qty - old_qty
    product.quantity = new_qty
    product.save(update_fields=["quantity", "updated_at"])
    if delta != 0:
      StockOperation.objects.create(
        product=product,
        operation_type=StockOperation.OperationType.INTAKE if delta > 0 else StockOperation.OperationType.ADJUSTMENT,
        quantity=abs(delta),
        performed_by=user,
        comment=f"Приёмка по артикулам: остаток {old_qty} → {new_qty}",
      )
    updated += 1

  _recalc_session_totals(session)
  session.active_group_key = group_key
  session.save(update_fields=["active_group_key"])
  return {
    "updated": updated,
    "group_key": group_key,
    "session": serialize_session(session),
  }


@transaction.atomic
def delete_intake_product(
  session: ArticleIntakeSession,
  *,
  product_id: int,
  user=None,
) -> dict:
  session = _require_editable(
    ArticleIntakeSession.objects.select_for_update().select_related("seller").get(pk=session.pk)
  )
  product = (
    _session_product_qs(session)
    .select_for_update()
    .filter(pk=product_id)
    .select_related("cell")
    .first()
  )
  if not product:
    raise ArticleIntakeError("Товар не найден в этой приёмке")

  group_key = product.article_group_key
  barcode = product.barcode
  cell_number = product.cell.number if product.cell_id else ""
  _delete_product_and_cell(product)

  remaining = _session_product_qs(session).filter(article_group_key=group_key).count()
  keys = list(session.confirmed_group_keys or [])
  if remaining == 0 and group_key in keys:
    keys = [key for key in keys if key != group_key]
    session.confirmed_group_keys = keys
    if session.active_group_key == group_key:
      session.active_group_key = keys[-1] if keys else ""

  _recalc_session_totals(session)
  session.save(update_fields=["confirmed_group_keys", "active_group_key", "total_units"])

  AuditLog.objects.create(
    user=user,
    seller=session.seller,
    action_type=AuditLog.ActionType.INTAKE,
    message=f"Приёмка по артикулам #{session.id}: удалён баркод {barcode}, яч. {cell_number}",
    details={"product_id": product_id, "group_key": group_key},
  )
  return {"deleted": True, "session": serialize_session(session)}


def _ozon_stock_amount(client, offer_id: str, warehouse_id: int) -> int:
  rows = client.fbs_stocks_by_offer_ids([offer_id])
  for row in rows:
    try:
      wh_id = int(row.get("warehouse_id") or 0)
    except (TypeError, ValueError):
      continue
    if wh_id != warehouse_id:
      continue
    try:
      return max(0, int(row.get("present") or 0))
    except (TypeError, ValueError):
      return 0
  return 0


@transaction.atomic
def push_to_marketplace(
  session: ArticleIntakeSession,
  *,
  warehouse_id: int,
  mode: str,
  user=None,
) -> dict:
  session = ArticleIntakeSession.objects.select_related("seller").get(pk=session.pk)
  seller = session.seller
  mp = normalize_marketplace(session.marketplace)
  mode = (mode or PUSH_MODE_REPLACE).strip().lower()
  if mode not in {PUSH_MODE_REPLACE, PUSH_MODE_ADD}:
    raise ArticleIntakeError("Режим: replace или add")

  if session.marketplace_pushed_at:
    raise ArticleIntakeError("Остатки уже выгружались на маркетплейс")

  group_keys = session.confirmed_group_keys or []
  products = list(
    Product.objects.filter(
      seller=seller,
      marketplace=mp,
      article_group_key__in=group_keys,
      quantity__gt=0,
    ).select_related("cell")
  )
  if not products:
    raise ArticleIntakeError("Нет товаров с остатком для выгрузки")

  updated = 0
  errors: list[dict] = []

  if mp == WB:
    warehouse = get_seller_warehouse(seller, warehouse_id)
    for product in products:
      barcode = product.barcode.strip()
      crm_qty = int(product.quantity or 0)
      if crm_qty <= 0:
        continue
      try:
        if mode == PUSH_MODE_REPLACE:
          set_wb_stock_absolute(seller, warehouse, barcode, crm_qty)
          new_amount = crm_qty
        else:
          result = push_wb_stock_increment(seller, warehouse, barcode, crm_qty)
          new_amount = int(result.get("new_wb_amount") or 0)
        updated += 1
      except WBStockError as exc:
        errors.append({"barcode": barcode, "error": str(exc)})
  else:
    warehouse = SellerOzonWarehouse.objects.filter(pk=warehouse_id, seller=seller).first()
    if not warehouse:
      raise ArticleIntakeError("Склад Ozon не найден")
    try:
      client = ozon_client_for_seller(seller)
    except OzonCountsError as exc:
      raise ArticleIntakeError(str(exc)) from exc

    stocks = []
    for product in products:
      offer_id = (product.vendor_code or product.barcode or "").strip()
      crm_qty = int(product.quantity or 0)
      if not offer_id or crm_qty <= 0:
        continue
      amount = crm_qty
      if mode == PUSH_MODE_ADD:
        current = _ozon_stock_amount(client, offer_id, warehouse.ozon_warehouse_id)
        amount = current + crm_qty
      stocks.append({
        "offer_id": offer_id,
        "stock": amount,
        "warehouse_id": warehouse.ozon_warehouse_id,
      })
    if not stocks:
      raise ArticleIntakeError("Нет артикулов для отправки на Ozon")
    try:
      raw = client.update_stocks(stocks)
    except OzonApiError as exc:
      raise ArticleIntakeError(str(exc)) from exc
    for row in raw:
      ok = row.get("updated")
      if ok is True or str(ok).lower() == "true":
        updated += 1
      else:
        errors.append({
          "offer_id": row.get("offer_id") or "",
          "error": str(row.get("errors") or row.get("error") or row)[:240],
        })
    if not raw:
      updated = len(stocks)

  if updated > 0 and not errors:
    session.marketplace_pushed_at = timezone.now()
    session.save(update_fields=["marketplace_pushed_at"])

  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.OTHER,
    message=(
      f"Приёмка по артикулам #{session.id}: выгрузка на {mp.upper()} "
      f"({mode}), обновлено {updated}"
    ),
    details={"warehouse_id": warehouse_id, "mode": mode, "errors": errors[:20]},
  )

  return {
    "updated": updated,
    "errors": errors[:20],
    "error_count": len(errors),
    "mode": mode,
    "locked": bool(session.marketplace_pushed_at),
    "session": serialize_session(session),
    "message": (
      f"Обновлено {updated} позиций"
      + (f", ошибок: {len(errors)}" if errors else "")
    ),
  }


@transaction.atomic
def complete_session(session: ArticleIntakeSession, *, user=None) -> ArticleIntakeSession:
  session = _require_active(
    ArticleIntakeSession.objects.select_for_update().select_related("seller").get(pk=session.pk)
  )
  if not session.confirmed_group_keys:
    raise ArticleIntakeError("Нет подтверждённых групп — сначала отсканируйте товары")
  session.status = ArticleIntakeSession.Status.COMPLETED
  session.completed_at = timezone.now()
  session.save(update_fields=["status", "completed_at"])
  AuditLog.objects.create(
    user=user,
    seller=session.seller,
    action_type=AuditLog.ActionType.INTAKE,
    message=f"Приёмка по артикулам #{session.id} завершена",
    details=serialize_session(session),
  )
  return session
