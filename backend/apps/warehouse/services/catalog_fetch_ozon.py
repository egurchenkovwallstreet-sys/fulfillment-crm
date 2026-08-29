"""Загрузка каталога Ozon FBS и план ячеек (как онбординг WB)."""
from __future__ import annotations

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


def _color_from_attributes(raw: dict) -> str:
  for attr in raw.get("attributes") or []:
    if not isinstance(attr, dict):
      continue
    name = str(attr.get("name") or "").lower()
    if "цвет" not in name and "color" not in name:
      continue
    values = attr.get("values") or []
    if values and isinstance(values[0], dict):
      return str(values[0].get("value") or values[0].get("value_id") or "").strip()
    if values:
      return str(values[0]).strip()
  return ""


def _size_from_attributes(raw: dict) -> str:
  for attr in raw.get("attributes") or []:
    if not isinstance(attr, dict):
      continue
    name = str(attr.get("name") or "").lower()
    if "размер" not in name and name not in {"size", "sizes"}:
      continue
    values = attr.get("values") or []
    if values and isinstance(values[0], dict):
      return str(values[0].get("value") or values[0].get("value_id") or "").strip()
    if values:
      return str(values[0]).strip()
  return ""


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
  for attr in raw.get("attributes") or []:
    if not isinstance(attr, dict):
      continue
    name = str(attr.get("name") or "").lower()
    if "честн" in name or "киз" in name or "datamatrix" in name:
      values = attr.get("values") or []
      text = " ".join(str(item.get("value") if isinstance(item, dict) else item) for item in values).lower()
      if any(flag in text for flag in ("да", "true", "1", "обязател")):
        return True
  return False


def _parse_cards_to_items(cards: list[dict]) -> list[CatalogBarcodeItem]:
  items: list[CatalogBarcodeItem] = []
  seen: set[str] = set()
  for card in cards:
    article_id = _article_id(card)
    if not article_id:
      continue
    title = str(card.get("name") or "").strip()
    vendor_code = str(card.get("offer_id") or "").strip()
    photo_url = _photo_url(card)
    tech_size = _size_from_attributes(card)
    color_label = _color_from_attributes(card)
    requires_marking = _requires_marking(card)
    barcodes = _barcodes(card)
    if not barcodes:
      continue
    for barcode in barcodes:
      if barcode in seen:
        continue
      seen.add(barcode)
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
  items.sort(key=lambda item: (item.wb_nm_id, item.color_label.lower(), size_sort_key(item.tech_size, item.wb_size), item.barcode))
  return items


def fetch_ozon_catalog_items(seller: Seller) -> list[CatalogBarcodeItem]:
  """Каталог Ozon селлера для поиска групп артикул+цвет."""
  try:
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
  except (OzonCountsError, OzonApiError) as exc:
    raise CatalogError(str(exc)) from exc
  if not cards and short:
    cards = short
  return _parse_cards_to_items(cards)


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
    short = client.product_list_ids()
    product_ids = []
    for row in short:
      try:
        product_ids.append(int(row.get("product_id") or row.get("id") or 0))
      except (TypeError, ValueError):
        continue
    product_ids = [item for item in product_ids if item]
    cards = client.product_info_list(product_ids) if product_ids else []
  except (OzonCountsError, OzonApiError) as exc:
    raise CatalogError(str(exc)) from exc

  if not cards and short:
    cards = short
  flat_items = _parse_cards_to_items(cards)
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
