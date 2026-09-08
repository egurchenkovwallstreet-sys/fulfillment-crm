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
from apps.warehouse.services.catalog_fetch import CatalogError, barcode_lookup_variants, normalize_barcode
from apps.warehouse.services.catalog_fetch_ozon import fetch_ozon_item_by_barcode
from apps.warehouse.services.catalog_groups import (
  find_group_by_barcode,
  group_key_for_item,
  serialize_group_preview,
)
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


def _find_product_by_barcode(seller: Seller, marketplace: str, barcode: str) -> Product | None:
  mp = normalize_marketplace(marketplace)
  for variant in barcode_lookup_variants(barcode, mp):
    product = (
      Product.objects.filter(seller=seller, marketplace=mp, barcode=variant)
      .select_related("cell")
      .first()
    )
    if product:
      return product
  return None


def _product_in_session(session: ArticleIntakeSession, product: Product | None) -> bool:
  if not product:
    return False
  group_key = (product.article_group_key or "").strip()
  if not group_key:
    return False
  return group_key in (session.confirmed_group_keys or [])


def _group_has_session_cells(session: ArticleIntakeSession, group_key: str) -> bool:
  if not group_key:
    return False
  return _session_product_qs(session).filter(article_group_key=group_key).exists()


def _existing_products_map(seller: Seller, marketplace: str) -> dict[str, Product]:
  mp = normalize_marketplace(marketplace)
  by_barcode: dict[str, Product] = {}
  for product in Product.objects.filter(seller=seller, marketplace=mp).select_related("cell"):
    by_barcode[product.barcode] = product
    if mp == OZON:
      for alias in barcode_lookup_variants(product.barcode, mp):
        by_barcode.setdefault(alias, product)
  return by_barcode


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
  product = _find_product_by_barcode(seller, mp, barcode)

  if product and _product_in_session(session, product):
    if mode == "increment":
      return increment_product(session, barcode=product.barcode, user=user)
    return {
      "action": "known",
      "product": _serialize_product(product),
      "session": serialize_session(session),
    }

  if mp == OZON:
    return _preview_ozon_barcode(session, seller, barcode)

  try:
    anchor, group_items, meta = find_group_by_barcode(seller, mp, barcode)
  except CatalogError as exc:
    raise ArticleIntakeError(str(exc)) from exc

  group_key = str(meta.get("group_key") or group_key_for_item(mp, anchor))

  if _group_has_session_cells(session, group_key):
    if product and _product_in_session(session, product):
      if mode == "increment":
        return increment_product(session, barcode=product.barcode, user=user)
      return {
        "action": "known",
        "product": _serialize_product(product),
        "session": serialize_session(session),
      }
    raise ArticleIntakeError(
      "Группа уже создана в этой приёмке — отсканируйте баркод для +1 или введите количество",
    )

  existing_map = _existing_products_map(seller, mp)
  existing_barcodes = set(existing_map)
  start_cell = int(_next_cell_number(seller, mp))
  cell_numbers: dict[str, str] = {}
  num = start_cell
  for item in group_items:
    existing_product = existing_map.get(item.barcode)
    if existing_product and existing_product.cell_id:
      cell_numbers[item.barcode] = existing_product.cell.number
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


def _preview_ozon_barcode(session: ArticleIntakeSession, seller: Seller, barcode: str) -> dict:
  try:
    item, meta = fetch_ozon_item_by_barcode(seller, barcode)
  except CatalogError as exc:
    raise ArticleIntakeError(str(exc)) from exc

  group_key = str(meta.get("group_key") or f"ozon:barcode:{item.barcode}")
  if _group_has_session_cells(session, group_key):
    product = _find_product_by_barcode(seller, OZON, item.barcode)
    if product and _product_in_session(session, product):
      return {
        "action": "known",
        "product": _serialize_product(product),
        "session": serialize_session(session),
      }
    raise ArticleIntakeError("Этот баркод уже принят в этой сессии — измените количество в таблице")

  existing_map = _existing_products_map(seller, OZON)
  existing = existing_map.get(item.barcode)
  if existing and int(existing.quantity or 0) > 0 and not _product_in_session(session, existing):
    raise ArticleIntakeError(
      f"Баркод {item.barcode} уже на складе CRM ({existing.quantity} шт., "
      f"яч. №{existing.cell.number if existing.cell_id else '—'}). "
      "Приёмка не создаёт вторую ячейку — правьте остаток в карточке товара."
    )
  cell_number = ""
  if existing and existing.cell_id:
    cell_number = existing.cell.number
  else:
    cell_number = str(_next_cell_number(seller, OZON))

  fbs_qty = int(meta.get("ozon_fbs_quantity") or 0)
  preview = serialize_group_preview(
    OZON,
    item,
    [item],
    scanned_barcode=item.barcode,
    scanned_quantity=fbs_qty,
    cell_numbers={item.barcode: cell_number},
    existing_barcodes={item.barcode} if existing else set(),
    article_label=str(meta.get("article_label") or item.vendor_code or item.barcode),
  )
  preview["group_key"] = group_key
  preview["ozon_fbs_quantity"] = fbs_qty
  preview["group_size"] = 1
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
  if normalize_marketplace(session.marketplace) == OZON:
    return _confirm_ozon_barcode(
      session,
      scanned_barcode=scanned_barcode,
      items=items,
      user=user,
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

  scan_variants = set(barcode_lookup_variants(scanned_barcode, mp))
  if scan_variants & excluded:
    raise ArticleIntakeError("Нельзя исключить отсканированный баркод")

  created_cells: list[str] = []
  created_products = 0
  created_items: list[dict] = []
  existing_map = _existing_products_map(seller, mp)

  for item in active_items:
    row = payload_by_barcode.get(item.barcode) or {}
    cell_number = str(row.get("cell_number") or "").strip()
    existing = existing_map.get(item.barcode)

    if existing:
      if _product_in_session(session, existing):
        created_items.append(_serialize_product(existing))
        continue
      other_qty = int(existing.quantity or 0)
      if other_qty > 0:
        raise ArticleIntakeError(
          f"Баркод {item.barcode} уже на складе ({other_qty} шт.) — "
          "нельзя пересоздать ячейку через приёмку",
        )
      if not cell_number:
        cell_number = existing.cell.number if existing.cell_id else _next_cell_number(seller, mp)
      cell, _ = Cell.objects.get_or_create(
        seller=seller,
        marketplace=mp,
        number=cell_number,
        defaults={"is_occupied": False},
      )
      existing.name = item.title
      existing.cell = cell
      existing.quantity = 0
      existing.requires_marking = item.requires_marking
      existing.wb_nm_id = item.wb_nm_id
      existing.vendor_code = item.vendor_code
      existing.tech_size = item.tech_size
      existing.wb_size = item.wb_size
      existing.photo_url = item.photo_url
      existing.color_label = item.color_label
      existing.article_group_key = group_key
      existing.save(
        update_fields=[
          "name",
          "cell",
          "quantity",
          "requires_marking",
          "wb_nm_id",
          "vendor_code",
          "tech_size",
          "wb_size",
          "photo_url",
          "color_label",
          "article_group_key",
          "updated_at",
        ]
      )
      refresh_cell_occupied(cell)
      if cell_number not in created_cells:
        created_cells.append(cell_number)
      created_products += 1
      created_items.append(_serialize_product(existing))
      continue

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


def _payload_quantity(row: dict) -> int:
  try:
    return max(0, int(row.get("quantity") or 0))
  except (TypeError, ValueError):
    return 0


def _set_product_quantity(product: Product, quantity: int, user, comment: str) -> None:
  old_qty = int(product.quantity or 0)
  new_qty = max(0, quantity)
  if new_qty == old_qty:
    return
  product.quantity = new_qty
  product.save(update_fields=["quantity", "updated_at"])
  delta = new_qty - old_qty
  StockOperation.objects.create(
    product=product,
    operation_type=StockOperation.OperationType.INTAKE if delta > 0 else StockOperation.OperationType.ADJUSTMENT,
    quantity=abs(delta),
    performed_by=user,
    comment=comment,
  )


def _confirm_ozon_barcode(
  session: ArticleIntakeSession,
  *,
  scanned_barcode: str,
  items: list[dict],
  user=None,
) -> dict:
  seller = session.seller
  scanned_barcode = normalize_barcode(scanned_barcode)
  try:
    item, meta = fetch_ozon_item_by_barcode(seller, scanned_barcode)
  except CatalogError as exc:
    raise ArticleIntakeError(str(exc)) from exc

  group_key = str(meta.get("group_key") or f"ozon:barcode:{item.barcode}")
  if group_key in (session.confirmed_group_keys or []):
    raise ArticleIntakeError("Этот баркод уже подтверждён в этой приёмке")

  payload_by_barcode = {
    normalize_barcode(str(row.get("barcode") or "")): row
    for row in items
    if normalize_barcode(str(row.get("barcode") or ""))
  }
  row = payload_by_barcode.get(item.barcode) or payload_by_barcode.get(scanned_barcode) or {}
  if row.get("excluded"):
    raise ArticleIntakeError("Нельзя исключить отсканированный баркод")
  quantity = _payload_quantity(row)
  cell_number = str(row.get("cell_number") or "").strip()

  existing_map = _existing_products_map(seller, OZON)
  existing = existing_map.get(item.barcode)

  if existing and _product_in_session(session, existing):
    raise ArticleIntakeError("Этот баркод уже принят в этой сессии")

  if existing and int(existing.quantity or 0) > 0 and not _product_in_session(session, existing):
    raise ArticleIntakeError(
      f"Баркод {item.barcode} уже на складе ({existing.quantity} шт.) — "
      "нельзя пересоздать ячейку через приёмку",
    )

  if existing:
    if not cell_number:
      cell_number = existing.cell.number if existing.cell_id else _next_cell_number(seller, OZON)
    cell, _ = Cell.objects.get_or_create(
      seller=seller,
      marketplace=OZON,
      number=cell_number,
      defaults={"is_occupied": False},
    )
    existing.name = item.title
    existing.cell = cell
    existing.requires_marking = item.requires_marking
    existing.wb_nm_id = item.wb_nm_id
    existing.vendor_code = item.vendor_code
    existing.tech_size = item.tech_size
    existing.wb_size = item.wb_size
    existing.photo_url = item.photo_url
    existing.color_label = item.color_label
    existing.article_group_key = group_key
    existing.save(
      update_fields=[
        "name",
        "cell",
        "requires_marking",
        "wb_nm_id",
        "vendor_code",
        "tech_size",
        "wb_size",
        "photo_url",
        "color_label",
        "article_group_key",
        "updated_at",
      ]
    )
    product = existing
  else:
    if not cell_number:
      cell_number = _next_cell_number(seller, OZON)
    cell, _ = Cell.objects.get_or_create(
      seller=seller,
      marketplace=OZON,
      number=cell_number,
      defaults={"is_occupied": False},
    )
    product = Product.objects.create(
      seller=seller,
      marketplace=OZON,
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

  _set_product_quantity(
    product,
    quantity,
    user,
    f"Приёмка Ozon: остаток CRM {quantity} шт. (FBS в ЛК: {meta.get('ozon_fbs_quantity') or 0})",
  )
  refresh_cell_occupied(product.cell)

  keys = list(session.confirmed_group_keys or [])
  keys.append(group_key)
  session.confirmed_group_keys = keys
  session.active_group_key = group_key
  session.scan_count += 1
  session.save(update_fields=["confirmed_group_keys", "active_group_key", "scan_count"])
  _recalc_session_totals(session)

  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.INTAKE,
    message=(
      f"Приёмка Ozon #{session.id}: баркод {item.barcode}, "
      f"яч. {product.cell.number if product.cell_id else '—'}, {quantity} шт."
    ),
    details={
      "session_id": session.id,
      "group_key": group_key,
      "barcode": item.barcode,
      "quantity": quantity,
      "ozon_fbs_quantity": meta.get("ozon_fbs_quantity") or 0,
    },
  )

  return {
    "group_key": group_key,
    "created_products": 1,
    "created_cells": [product.cell.number] if product.cell_id else [],
    "products": [_serialize_product(product)],
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
  product = None
  for variant in barcode_lookup_variants(barcode, session.marketplace):
    product = (
      _session_product_qs(session)
      .select_for_update()
      .filter(barcode=variant)
      .select_related("cell")
      .first()
    )
    if product:
      break
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
        try:
          current = _ozon_stock_amount(client, offer_id, warehouse.ozon_warehouse_id)
        except OzonApiError as exc:
          raise ArticleIntakeError(str(exc)) from exc
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
def delete_session(session: ArticleIntakeSession, *, user=None) -> dict:
  session = (
    ArticleIntakeSession.objects.select_for_update()
    .select_related("seller")
    .get(pk=session.pk)
  )
  if session.marketplace_pushed_at:
    raise ArticleIntakeError(
      "Нельзя удалить приёмку после выгрузки остатков на маркетплейс",
    )
  seller = session.seller
  session_id = session.id
  seller_name = seller.company_name
  deleted_products = 0
  for product in list(_session_product_qs(session).select_related("cell")):
    _delete_product_and_cell(product)
    deleted_products += 1
  session.delete()
  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.INTAKE,
    message=(
      f"Приёмка по артикулам #{session_id} удалена "
      f"(«{seller_name}», товаров: {deleted_products})"
    ),
    details={"session_id": session_id, "deleted_products": deleted_products},
  )
  return {"deleted": True, "session_id": session_id, "deleted_products": deleted_products}


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
