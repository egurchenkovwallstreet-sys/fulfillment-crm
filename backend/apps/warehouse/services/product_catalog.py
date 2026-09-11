"""Подтягивание карточек МП в товары CRM: фото, размеры, артикулы."""
from __future__ import annotations

from apps.integrations.marketplace import OZON, WB, normalize_marketplace
from apps.integrations.wb_content import search_wb_card_by_barcode
from apps.sellers.models import Seller
from apps.warehouse.models import Product
from apps.warehouse.services.catalog_fetch import (
  CatalogBarcodeItem,
  CatalogError,
  _get_token,
  barcode_lookup_variants,
  normalize_barcode,
  parse_wb_card_to_items,
)
from apps.warehouse.services.catalog_fetch_ozon import (
  fetch_ozon_catalog_items,
  fetch_ozon_item_by_barcode,
  ozon_barcode_aliases,
)


CATALOG_PRODUCT_FIELDS = (
  "name",
  "requires_marking",
  "wb_nm_id",
  "vendor_code",
  "tech_size",
  "wb_size",
  "photo_url",
  "color_label",
  "updated_at",
)


def _safe_photo_url(url: str) -> str:
  text = str(url or "").strip()
  if text.startswith("http"):
    return text[:500]
  return ""


def catalog_item_for_barcode(
  items: list[CatalogBarcodeItem],
  barcode: str,
  marketplace: str,
) -> CatalogBarcodeItem | None:
  variants = set(barcode_lookup_variants(barcode, marketplace))
  for item in items:
    if item.barcode in variants:
      return item
  return None


def build_ozon_catalog_index(seller: Seller) -> dict[str, CatalogBarcodeItem]:
  index: dict[str, CatalogBarcodeItem] = {}
  for item in fetch_ozon_catalog_items(seller):
    index[item.barcode] = item
    for alias in ozon_barcode_aliases(item.barcode):
      index[alias] = item
  return index


def lookup_catalog_item_for_barcode(
  seller: Seller,
  barcode: str,
  marketplace: str = WB,
) -> CatalogBarcodeItem | None:
  """Найти карточку по баркоду. CatalogError — проблема токена/API."""
  mp = normalize_marketplace(marketplace)
  barcode = normalize_barcode(barcode)
  if not barcode:
    return None

  if mp == OZON:
    item, _meta = fetch_ozon_item_by_barcode(seller, barcode)
    return item

  token = _get_token(seller)
  card = search_wb_card_by_barcode(token, barcode)
  if not card:
    return None
  items = parse_wb_card_to_items(card)
  return catalog_item_for_barcode(items, barcode, mp)


def catalog_item_to_create_kwargs(
  item: CatalogBarcodeItem,
  *,
  name_override: str = "",
) -> dict:
  name = (name_override or item.title or "").strip()
  return {
    "name": name,
    "requires_marking": item.requires_marking,
    "wb_nm_id": item.wb_nm_id or None,
    "vendor_code": item.vendor_code or "",
    "tech_size": item.tech_size or "",
    "wb_size": item.wb_size or "",
    "photo_url": _safe_photo_url(item.photo_url),
    "color_label": item.color_label or "",
  }


def apply_catalog_item_to_product(product: Product, item: CatalogBarcodeItem) -> list[str]:
  """Записать поля карточки в товар. Возвращает список изменённых полей."""
  changed: list[str] = []

  if item.title and product.name != item.title:
    product.name = item.title
    changed.append("name")

  if product.requires_marking != item.requires_marking:
    product.requires_marking = item.requires_marking
    changed.append("requires_marking")

  if item.wb_nm_id and product.wb_nm_id != item.wb_nm_id:
    product.wb_nm_id = item.wb_nm_id
    changed.append("wb_nm_id")

  vendor_code = item.vendor_code or ""
  if vendor_code and product.vendor_code != vendor_code:
    product.vendor_code = vendor_code
    changed.append("vendor_code")

  tech_size = item.tech_size or ""
  if tech_size and product.tech_size != tech_size:
    product.tech_size = tech_size
    changed.append("tech_size")

  wb_size = item.wb_size or ""
  if wb_size and product.wb_size != wb_size:
    product.wb_size = wb_size
    changed.append("wb_size")

  photo_url = _safe_photo_url(item.photo_url)
  if photo_url and product.photo_url != photo_url:
    product.photo_url = photo_url
    changed.append("photo_url")

  color_label = item.color_label or ""
  if color_label and product.color_label != color_label:
    product.color_label = color_label
    changed.append("color_label")

  return changed


def try_enrich_product_from_catalog(
  product: Product,
  seller: Seller | None = None,
) -> bool:
  """Подтянуть карточку в товар без ошибки наружу. True — если что-то обновили."""
  seller = seller or product.seller
  try:
    item = lookup_catalog_item_for_barcode(seller, product.barcode, product.marketplace)
  except CatalogError:
    return False
  if not item:
    return False
  changed = apply_catalog_item_to_product(product, item)
  if not changed:
    return False
  update_fields = list(dict.fromkeys([*changed, "updated_at"]))
  product.save(update_fields=update_fields)
  return True


def create_kwargs_for_new_product(
  seller: Seller,
  barcode: str,
  marketplace: str,
  *,
  name_override: str = "",
) -> dict:
  """
  Поля карточки для Product.objects.create.
  CatalogError — ошибка API; если карточка не найдена — минимальный набор полей.
  """
  mp = normalize_marketplace(marketplace)
  item = lookup_catalog_item_for_barcode(seller, barcode, mp)
  if item:
    return catalog_item_to_create_kwargs(item, name_override=name_override)

  if mp == OZON:
    raise CatalogError("Баркод не найден в каталоге Ozon")

  from apps.warehouse.services.marking_lookup import lookup_marking_for_barcode

  marking = lookup_marking_for_barcode(seller, barcode)
  name = (name_override or marking.title or "").strip()
  return {
    "name": name,
    "requires_marking": marking.requires_marking if marking.wb_found else False,
    "vendor_code": "",
    "tech_size": "",
    "wb_size": "",
    "photo_url": "",
    "color_label": "",
    "wb_nm_id": None,
  }
