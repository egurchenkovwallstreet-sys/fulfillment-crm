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
  products_count = Product.objects.filter(
    seller=seller,
    marketplace=mp,
    article_group_key__in=session.confirmed_group_keys or [],
  ).count()
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
    "created_at": session.created_at.isoformat() if session.created_at else None,
    "completed_at": session.completed_at.isoformat() if session.completed_at else None,
    "can_scan": session.status == ArticleIntakeSession.Status.ACTIVE,
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
  quantity: int,
  user=None,
) -> dict:
  session = _require_active(
    ArticleIntakeSession.objects.select_for_update().select_related("seller").get(pk=session.pk)
  )
  seller = session.seller
  mp = session.marketplace
  barcode = normalize_barcode(barcode)
  if len(barcode) < 4:
    raise ArticleIntakeError("Баркод слишком короткий")
  if quantity < 0:
    raise ArticleIntakeError("Количество не может быть отрицательным")

  product = Product.objects.filter(seller=seller, marketplace=mp, barcode=barcode).first()
  if product:
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
    anchor, group_items = find_group_by_barcode(seller, mp, barcode)
  except CatalogError as exc:
    raise ArticleIntakeError(str(exc)) from exc

  group_key = group_key_for_item(mp, anchor)
  if quantity <= 0:
    raise ArticleIntakeError("Для новой группы укажите количество больше 0")

  if group_key in (session.confirmed_group_keys or []):
    raise ArticleIntakeError(
      "Группа уже создана, но баркод отсутствует в CRM — обратитесь к администратору",
    )

  if Product.objects.filter(seller=seller, marketplace=mp, article_group_key=group_key).exists():
    raise ArticleIntakeError(
      "Группа артикул+цвет уже есть в CRM, но этот баркод не найден",
    )

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
    scanned_quantity=quantity,
    cell_numbers=cell_numbers,
    existing_barcodes=existing_barcodes,
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
  session = _require_active(
    ArticleIntakeSession.objects.select_for_update().select_related("seller").get(pk=session.pk)
  )
  seller = session.seller
  mp = session.marketplace
  scanned_barcode = normalize_barcode(scanned_barcode)
  if scanned_quantity <= 0:
    raise ArticleIntakeError("Количество должно быть больше 0")

  try:
    anchor, group_items = find_group_by_barcode(seller, mp, scanned_barcode)
  except CatalogError as exc:
    raise ArticleIntakeError(str(exc)) from exc

  group_key = group_key_for_item(mp, anchor)
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
  added_units = 0

  for item in active_items:
    if Product.objects.filter(seller=seller, marketplace=mp, barcode=item.barcode).exists():
      raise ArticleIntakeError(f"Баркод {item.barcode} уже есть в CRM")

    row = payload_by_barcode.get(item.barcode) or {}
    cell_number = str(row.get("cell_number") or "").strip()
    if not cell_number:
      cell_number = _next_cell_number(seller, mp)

    qty = scanned_quantity if item.barcode == scanned_barcode else 0

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
      quantity=qty,
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
    added_units += qty
    if qty > 0:
      StockOperation.objects.create(
        product=product,
        operation_type=StockOperation.OperationType.INTAKE,
        quantity=qty,
        performed_by=user,
        comment=(
          f"Приёмка по артикулам: артикул {item.vendor_code or item.wb_nm_id}, "
          f"цвет {item.color_label or '—'}, яч. {cell_number}"
        ),
      )

  keys = list(session.confirmed_group_keys or [])
  keys.append(group_key)
  session.confirmed_group_keys = keys
  session.scan_count += 1
  session.total_units += added_units
  session.save(update_fields=["confirmed_group_keys", "scan_count", "total_units"])

  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.INTAKE,
    message=(
      f"Приёмка по артикулам #{session.id}: группа {anchor.vendor_code or anchor.wb_nm_id} "
      f"({anchor.color_label or '—'}), {created_products} ячеек, +{added_units} шт."
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
    "added_units": added_units,
    "session": serialize_session(session),
  }


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
