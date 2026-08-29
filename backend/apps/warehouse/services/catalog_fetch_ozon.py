"""Загрузка каталога Ozon FBS и план ячеек (как онбординг WB)."""
from __future__ import annotations

import re

from apps.integrations.marketplace import OZON
from apps.integrations.ozon_client import OzonApiError
from apps.orders.services.ozon_counts import OzonCountsError, ozon_client_for_seller
from apps.sellers.models import Seller, SellerOzonWarehouse
from apps.warehouse.models import Product
from apps.warehouse.services.catalog_fetch import (
  CATALOG_MODE_WITH_STOCK,
  CatalogBarcodeItem,
  CatalogError,
  _assign_cell_numbers,
  _group_by_article,
  _serialize_article,
  _serialize_item,
  normalize_barcode,
)
from apps.warehouse.services.cells import _next_cell_number
from apps.warehouse.services.size_sort import size_sort_key

OZON_COLOR_ATTR_IDS = {10096, 10097, 8229}
OZON_SIZE_ATTR_IDS = {9535, 9508, 9456, 9455}

# Артикул продавца вида «0331коричневый 56» → база 0331, цвет коричневый, размер 56.
_VENDOR_CODE_PARTS_RE = re.compile(
  r"^(?P<base>\d+)(?P<color>[а-яА-ЯёЁa-zA-Z]+)(?:[\s_-]+(?P<size>\d{1,3}))?$",
  re.UNICODE,
)


def _parse_vendor_code(vendor_code: str) -> tuple[str, str, str] | None:
  text = (vendor_code or "").strip()
  if not text:
    return None
  match = _VENDOR_CODE_PARTS_RE.match(text)
  if not match:
    return None
  base = match.group("base") or ""
  color = (match.group("color") or "").strip()
  size = (match.group("size") or "").strip()
  if not base or not color or color.isdigit():
    return None
  return base, color, size


def _color_from_vendor_code(vendor_code: str) -> str:
  parsed = _parse_vendor_code(vendor_code)
  return parsed[1] if parsed else ""


def _size_from_vendor_code(vendor_code: str) -> str:
  parsed = _parse_vendor_code(vendor_code)
  return parsed[2] if parsed else ""


def _base_article_from_vendor_code(vendor_code: str) -> str:
  parsed = _parse_vendor_code(vendor_code)
  return parsed[0] if parsed else ""


def _color_for_card(vendor_code: str, raw: dict) -> str:
  color = _color_from_attributes(raw)
  if color:
    return color
  color = _color_from_vendor_code(vendor_code)
  if color:
    return color
  return _color_from_name(raw)


def _resolve_ozon_color(item: CatalogBarcodeItem, raw: dict | None = None) -> str:
  color = (item.color_label or "").strip()
  if color:
    return color
  color = _color_from_vendor_code(item.vendor_code)
  if color:
    return color
  if raw:
    color = _color_from_attributes(raw)
  if color:
    return color
  if raw:
    color = _color_from_name(raw)
  return color


def _resolve_ozon_size(vendor_code: str, raw: dict) -> str:
  size = _size_from_attributes(raw)
  if size:
    return size
  return _size_from_vendor_code(vendor_code)


def _product_pk(raw: dict) -> int:
  try:
    return int(raw.get("id") or raw.get("product_id") or 0)
  except (TypeError, ValueError):
    return 0


def _attribute_values(attr: dict) -> list[str]:
  values: list[str] = []
  for item in attr.get("values") or []:
    if isinstance(item, dict):
      text = str(item.get("value") or item.get("dictionary_value") or "").strip()
    else:
      text = str(item).strip()
    if text:
      values.append(text)
  single = str(attr.get("value") or "").strip()
  if single:
    values.append(single)
  return values


def _iter_attributes(raw: dict):
  for attr in raw.get("attributes") or []:
    if isinstance(attr, dict):
      yield attr
  for block in raw.get("complex_attributes") or []:
    if isinstance(block, dict):
      for attr in block.get("attributes") or []:
        if isinstance(attr, dict):
          yield attr
    elif isinstance(block, list):
      for attr in block:
        if isinstance(attr, dict):
          yield attr


def _match_attribute(attr: dict, *, kind: str) -> str:
  try:
    attr_id = int(attr.get("id") or attr.get("attribute_id") or 0)
  except (TypeError, ValueError):
    attr_id = 0
  name = str(attr.get("name") or attr.get("attribute_name") or "").lower()

  if kind == "color":
    is_match = attr_id in OZON_COLOR_ATTR_IDS or "цвет" in name or name == "color"
  else:
    is_match = (
      attr_id in OZON_SIZE_ATTR_IDS
      or "размер" in name
      or name in {"size", "sizes", "размер производителя", "российский размер"}
    )
  if not is_match:
    return ""
  values = _attribute_values(attr)
  return values[0] if values else ""


def _color_from_name(raw: dict) -> str:
  name = str(raw.get("name") or "").strip()
  if not name:
    return ""
  parts = [part.strip() for part in name.split(",") if part.strip()]
  if len(parts) >= 2:
    candidate = parts[-2]
    if not re.search(r"\d", candidate) and len(candidate) <= 40:
      return candidate
  return ""


def _size_from_name(raw: dict) -> str:
  name = str(raw.get("name") or "").strip()
  if not name:
    return ""
  parts = [part.strip() for part in name.split(",") if part.strip()]
  if parts:
    tail = parts[-1]
    if re.search(r"\d", tail) or re.fullmatch(
      r"(?i)(xxs|xs|s|m|l|xl|xxl|xxxl|2xl|3xl|4xl|5xl|onesize|one size)",
      tail.replace(" ", ""),
    ):
      return tail
  return ""


def _color_from_attributes(raw: dict) -> str:
  for attr in _iter_attributes(raw):
    value = _match_attribute(attr, kind="color")
    if value:
      return value
  return _color_from_name(raw)


def _size_from_attributes(raw: dict) -> str:
  for attr in _iter_attributes(raw):
    value = _match_attribute(attr, kind="size")
    if value:
      return value
  return _size_from_name(raw)


def _merge_attribute_cards(info_cards: list[dict], attr_cards: list[dict]) -> list[dict]:
  by_id: dict[int, dict] = {}
  for card in attr_cards:
    pk = _product_pk(card)
    if pk:
      by_id[pk] = card

  merged: list[dict] = []
  for card in info_cards:
    pk = _product_pk(card)
    attr_card = by_id.get(pk) or {}
    combined = dict(card)
    if attr_card.get("attributes"):
      combined["attributes"] = attr_card["attributes"]
    if attr_card.get("complex_attributes"):
      combined["complex_attributes"] = attr_card["complex_attributes"]
    if attr_card.get("name") and not combined.get("name"):
      combined["name"] = attr_card["name"]
    merged.append(combined)
  return merged


def _article_label(raw: dict, vendor_code: str) -> str:
  base = _base_article_from_vendor_code(vendor_code)
  if base:
    return base

  model = (raw.get("model_info") or {}) if isinstance(raw.get("model_info"), dict) else {}
  model_name = str(model.get("name") or "").strip()
  parsed_name = _parse_vendor_code(model_name)
  if parsed_name:
    return parsed_name[0]
  if model_name:
    return re.sub(r"[-_/]\d{1,3}([A-Za-z]{1,3})?$", "", model_name).strip() or model_name
  if vendor_code:
    return re.sub(r"[-_/]\d{1,3}([A-Za-z]{1,3})?$", "", vendor_code).strip() or vendor_code
  try:
    return str(int(model.get("model_id") or raw.get("id") or 0))
  except (TypeError, ValueError):
    return vendor_code or "—"


def _name_group_key(raw: dict) -> str:
  name = str(raw.get("name") or "").strip().lower()
  if not name:
    return ""
  text = re.sub(r",\s*(?:размер\s*)?\d{2,3}([/\-\d]*)?\s*$", "", name, flags=re.I)
  text = re.sub(
    r",\s*(xxs|xs|s|m|l|xl|xxl|xxxl|2xl|3xl|4xl|5xl)\s*$",
    "",
    text,
    flags=re.I,
  )
  return text.strip(" ,")


def ozon_group_key(item: CatalogBarcodeItem, raw: dict | None = None) -> str:
  color = _resolve_ozon_color(item, raw).strip().lower()
  if color:
    return f"ozon:{item.wb_nm_id}:{color}"
  return f"ozon:{item.wb_nm_id}:offer:{item.vendor_code or item.barcode}"


def resolve_seller_ozon_warehouses(
  seller: Seller,
  warehouse_ids: list[int] | None,
) -> list[SellerOzonWarehouse]:
  qs = SellerOzonWarehouse.objects.filter(seller=seller)
  if warehouse_ids:
    qs = qs.filter(pk__in=warehouse_ids)
  warehouses = list(qs.order_by("name", "id"))
  if not warehouses:
    raise CatalogError("Выберите хотя бы один склад Ozon FBS")
  return warehouses


def _photo_url(raw: dict) -> str:
  img = raw.get("primary_image")
  if isinstance(img, list) and img:
    first = img[0]
    if isinstance(first, str) and first.strip():
      return first.strip()[:500]
    if isinstance(first, dict):
      return str(first.get("url") or first.get("file_name") or "")[:500]
  if isinstance(img, str) and img.strip():
    return img.strip()[:500]
  images = raw.get("images") or []
  if images:
    first = images[0]
    if isinstance(first, str) and first.strip():
      return first.strip()[:500]
    if isinstance(first, dict):
      return str(first.get("url") or first.get("file_name") or "")[:500]
  return ""


def _barcodes(raw: dict) -> list[str]:
  codes: list[str] = []
  barcodes = raw.get("barcodes") or []
  if isinstance(barcodes, str):
    barcodes = [part.strip() for part in barcodes.split(",") if part.strip()]
  for item in barcodes:
    value = normalize_barcode(str(item))
    if value and value not in codes:
      codes.append(value)
  single = normalize_barcode(str(raw.get("barcode") or ""))
  if single:
    for part in single.split(","):
      value = part.strip()
      if value and value not in codes:
        codes.append(value)
  offer_id = str(raw.get("offer_id") or "").strip()
  if not codes and offer_id:
    codes.append(offer_id)
  return codes


def _article_id(raw: dict) -> int:
  model = (raw.get("model_info") or {}) if isinstance(raw.get("model_info"), dict) else {}
  try:
    model_id = int(model.get("model_id") or 0)
  except (TypeError, ValueError):
    model_id = 0
  if model_id:
    return model_id
  try:
    return int(raw.get("id") or raw.get("product_id") or 0)
  except (TypeError, ValueError):
    return 0


def _requires_marking(raw: dict) -> bool:
  if raw.get("is_mandatory_mark") or raw.get("is_kiz"):
    return True
  for attr in _iter_attributes(raw):
    if not isinstance(attr, dict):
      continue
    name = str(attr.get("name") or "").lower()
    if "честн" in name or "киз" in name or "datamatrix" in name:
      values = attr.get("values") or []
      text = " ".join(str(item.get("value") if isinstance(item, dict) else item) for item in values).lower()
      if any(flag in text for flag in ("да", "true", "1", "обязател")):
        return True
  return False


def _load_ozon_cards(seller: Seller) -> list[dict]:
  client = ozon_client_for_seller(seller)
  short = client.product_list_ids()
  product_ids = []
  for row in short:
    try:
      product_ids.append(int(row.get("product_id") or row.get("id") or 0))
    except (TypeError, ValueError):
      continue
  product_ids = [item for item in product_ids if item]
  cards = client.product_info_list(product_ids) if product_ids else []
  if not cards and short:
    cards = short
  if cards and product_ids:
    try:
      attr_cards = client.product_info_attributes(product_ids=product_ids)
      cards = _merge_attribute_cards(cards, attr_cards)
    except OzonApiError:
      pass
  return cards


def _parse_cards_to_items(cards: list[dict]) -> tuple[list[CatalogBarcodeItem], dict[str, dict]]:
  items: list[CatalogBarcodeItem] = []
  card_by_barcode: dict[str, dict] = {}
  seen: set[str] = set()
  for card in cards:
    article_id = _article_id(card)
    if not article_id:
      continue
    title = str(card.get("name") or "").strip()
    vendor_code = str(card.get("offer_id") or "").strip()
    photo_url = _photo_url(card)
    tech_size = _resolve_ozon_size(vendor_code, card)
    color_label = _color_for_card(vendor_code, card)
    requires_marking = _requires_marking(card)
    barcodes = _barcodes(card)
    if not barcodes:
      continue
    for barcode in barcodes:
      if barcode in seen:
        continue
      seen.add(barcode)
      card_by_barcode[barcode] = card
      items.append(
        CatalogBarcodeItem(
          barcode=barcode,
          wb_nm_id=article_id,
          vendor_code=vendor_code,
          title=title,
          tech_size=tech_size,
          wb_size=tech_size,
          photo_url=photo_url,
          requires_marking=requires_marking,
          color_label=color_label,
        )
      )
  items.sort(
    key=lambda item: (
      item.wb_nm_id,
      item.color_label.lower(),
      size_sort_key(item.tech_size, item.wb_size),
      item.barcode,
    )
  )
  return items, card_by_barcode


def fetch_ozon_catalog_items(seller: Seller) -> list[CatalogBarcodeItem]:
  """Каталог Ozon селлера для поиска групп артикул+цвет."""
  try:
    cards = _load_ozon_cards(seller)
  except (OzonCountsError, OzonApiError) as exc:
    raise CatalogError(str(exc)) from exc
  items, _ = _parse_cards_to_items(cards)
  return items


def fetch_ozon_group_by_barcode(
  seller: Seller,
  barcode: str,
) -> tuple[CatalogBarcodeItem, list[CatalogBarcodeItem], dict]:
  barcode = normalize_barcode(barcode)
  if not barcode:
    raise CatalogError("Пустой баркод")
  try:
    cards = _load_ozon_cards(seller)
  except (OzonCountsError, OzonApiError) as exc:
    raise CatalogError(str(exc)) from exc
  items, card_by_barcode = _parse_cards_to_items(cards)
  anchor = next((item for item in items if item.barcode == barcode), None)
  if not anchor:
    raise CatalogError("Баркод не найден в каталоге Ozon")

  anchor_card = card_by_barcode.get(anchor.barcode)
  anchor_key = ozon_group_key(anchor, anchor_card)
  grouped = []
  for item in items:
    item_card = card_by_barcode.get(item.barcode)
    if ozon_group_key(item, item_card) == anchor_key:
      grouped.append(item)
  grouped.sort(key=lambda item: (size_sort_key(item.tech_size, item.wb_size), item.barcode))

  article_label = _article_label(anchor_card or {}, anchor.vendor_code)
  return anchor, grouped, {
    "article_label": article_label,
    "group_size": len(grouped),
    "group_key": anchor_key,
  }


def _stock_map(
  rows: list[dict],
  warehouses: list[SellerOzonWarehouse],
) -> dict[str, dict]:
  ozon_to_crm = {wh.ozon_warehouse_id: wh.id for wh in warehouses}
  allowed = set(ozon_to_crm)
  result: dict[str, dict] = {}
  for row in rows:
    try:
      warehouse_id = int(row.get("warehouse_id") or 0)
    except (TypeError, ValueError):
      continue
    if allowed and warehouse_id not in allowed:
      continue
    try:
      present = max(0, int(row.get("present") or 0))
    except (TypeError, ValueError):
      present = 0
    keys = [
      str(row.get("offer_id") or "").strip(),
      str(row.get("sku") or "").strip(),
    ]
    crm_pk = ozon_to_crm.get(warehouse_id)
    if crm_pk is None:
      continue
    for key in keys:
      if not key:
        continue
      bucket = result.setdefault(key, {"total": 0, "by_warehouse": {}})
      bucket["by_warehouse"][crm_pk] = bucket["by_warehouse"].get(crm_pk, 0) + present
  for bucket in result.values():
    bucket["total"] = sum(bucket["by_warehouse"].values())
  return result


def build_ozon_onboarding_preview(
  seller: Seller,
  *,
  catalog_mode: str = "all",
  warehouse_ids: list[int] | None = None,
) -> dict:
  warehouses = resolve_seller_ozon_warehouses(seller, warehouse_ids)
  try:
    client = ozon_client_for_seller(seller)
    cards = _load_ozon_cards(seller)
  except (OzonCountsError, OzonApiError) as exc:
    raise CatalogError(str(exc)) from exc

  flat_items, _ = _parse_cards_to_items(cards)
  if not flat_items:
    raise CatalogError("В Ozon не найдено карточек с баркодом или артикулом")

  offer_ids = [item.vendor_code for item in flat_items if item.vendor_code]
  stock_rows: list[dict] = []
  try:
    stock_rows = client.fbs_stocks_by_offer_ids(offer_ids)
    if not stock_rows:
      skus = [str(card.get("sku") or "") for card in cards if card.get("sku")]
      if skus:
        stock_rows = client.fbs_stocks_by_skus(skus)
  except OzonApiError as exc:
    if catalog_mode == CATALOG_MODE_WITH_STOCK:
      raise CatalogError(f"Не удалось получить остатки Ozon: {exc}") from exc
    stock_rows = []

  stocks = _stock_map(stock_rows, warehouses)
  for item in flat_items:
    stock = stocks.get(item.vendor_code) or stocks.get(item.barcode) or {}
    item.wb_stock_total = int(stock.get("total") or 0)
    item.wb_stock_by_warehouse = dict(stock.get("by_warehouse") or {})

  articles = _group_by_article(flat_items)
  if catalog_mode == CATALOG_MODE_WITH_STOCK:
    articles = [
      article
      for article in articles
      if any(item.wb_stock_total >= 1 for item in article.items)
    ]
    kept = {item.barcode for article in articles for item in article.items}
    flat_items = [item for item in flat_items if item.barcode in kept]

  existing_barcodes = set(
    Product.objects.filter(seller=seller, marketplace=OZON).values_list("barcode", flat=True)
  )
  for item in flat_items:
    item.already_in_crm = item.barcode in existing_barcodes

  new_items = [item for item in flat_items if not item.already_in_crm]
  start_from = int(_next_cell_number(seller, OZON))
  _assign_cell_numbers(new_items, start_from=start_from)

  return {
    "seller_id": seller.id,
    "marketplace": OZON,
    "catalog_mode": catalog_mode,
    "next_cell_number": start_from,
    "cards_count": len({item.wb_nm_id for item in flat_items}),
    "barcodes_count": len(flat_items),
    "new_barcodes_count": len(new_items),
    "existing_barcodes_count": len([item for item in flat_items if item.already_in_crm]),
    "filtered_articles_count": len(articles),
    "warehouses": [
      {
        "id": wh.id,
        "ozon_warehouse_id": wh.ozon_warehouse_id,
        "wb_warehouse_id": wh.ozon_warehouse_id,
        "name": wh.name,
        "is_enabled": wh.is_enabled,
      }
      for wh in warehouses
    ],
    "articles": [_serialize_article(article) for article in articles],
    "items": [_serialize_item(item) for item in flat_items],
  }
