"""Загрузка каталога WB и построение плана ячеек."""
from __future__ import annotations

from dataclasses import dataclass, field

from apps.integrations.wb_client import WBApiError
from apps.integrations.wb_content import _pick_photo_url, fetch_all_seller_cards
from apps.integrations.wb_crypto import TokenCryptoError, decrypt_token
from apps.sellers.models import Seller, SellerWarehouse
from apps.warehouse.models import Product
from apps.warehouse.services.size_sort import size_sort_key
from apps.warehouse.services.wb_stocks import (
  WBStockError,
  fetch_wb_stocks_for_warehouses,
)

CATALOG_MODE_ALL = "all"
CATALOG_MODE_WITH_STOCK = "with_stock"


class CatalogError(Exception):
  pass


@dataclass
class CatalogBarcodeItem:
  barcode: str
  wb_nm_id: int
  vendor_code: str
  title: str
  tech_size: str
  wb_size: str
  photo_url: str
  requires_marking: bool
  wb_stock_total: int = 0
  wb_stock_by_warehouse: dict[int, int] = field(default_factory=dict)
  cell_number: str = ""
  already_in_crm: bool = False


@dataclass
class CatalogArticle:
  wb_nm_id: int
  vendor_code: str
  title: str
  photo_url: str
  requires_marking: bool
  items: list[CatalogBarcodeItem] = field(default_factory=list)


def _get_token(seller: Seller) -> str:
  if not seller.wb_api_token_encrypted:
    raise CatalogError(f"У селлера «{seller.company_name}» не задан токен WB")
  try:
    return decrypt_token(seller.wb_api_token_encrypted)
  except TokenCryptoError as exc:
    raise CatalogError(str(exc)) from exc


def _parse_cards_to_items(cards: list[dict]) -> list[CatalogBarcodeItem]:
  items: list[CatalogBarcodeItem] = []
  seen_barcodes: set[str] = set()

  for card in cards:
    nm_id = card.get("nmID")
    if nm_id is None:
      continue
    nm_id = int(nm_id)
    title = str(card.get("title") or card.get("subjectName") or "").strip()
    vendor_code = str(card.get("vendorCode") or "").strip()
    photo_url = _pick_photo_url(card)
    need_kiz = bool(card.get("needKiz"))

    size_rows: list[tuple[str, str, list[str]]] = []
    for size in card.get("sizes") or []:
      tech_size = str(size.get("techSize") or "").strip()
      wb_size = str(size.get("wbSize") or "").strip()
      skus = [str(sku).strip() for sku in (size.get("skus") or []) if str(sku).strip()]
      if skus:
        size_rows.append((wb_size, tech_size, skus))

    size_rows.sort(key=lambda row: size_sort_key(row[1], row[0]))

    for wb_size, tech_size, skus in size_rows:
      for barcode in skus:
        if barcode in seen_barcodes:
          continue
        seen_barcodes.add(barcode)
        items.append(
          CatalogBarcodeItem(
            barcode=barcode,
            wb_nm_id=nm_id,
            vendor_code=vendor_code,
            title=title,
            tech_size=tech_size,
            wb_size=wb_size,
            photo_url=photo_url,
            requires_marking=need_kiz,
          )
        )

  return items


def _group_by_article(items: list[CatalogBarcodeItem]) -> list[CatalogArticle]:
  by_nm: dict[int, CatalogArticle] = {}
  order: list[int] = []
  for item in items:
    if item.wb_nm_id not in by_nm:
      by_nm[item.wb_nm_id] = CatalogArticle(
        wb_nm_id=item.wb_nm_id,
        vendor_code=item.vendor_code,
        title=item.title,
        photo_url=item.photo_url,
        requires_marking=item.requires_marking,
      )
      order.append(item.wb_nm_id)
    article = by_nm[item.wb_nm_id]
    article.items.append(item)
    if item.requires_marking:
      article.requires_marking = True
  return [by_nm[nm_id] for nm_id in order]


def _assign_cell_numbers(items: list[CatalogBarcodeItem], start_from: int = 1) -> None:
  num = start_from
  for item in items:
    item.cell_number = str(num)
    num += 1


def build_seller_catalog_index(seller: Seller) -> dict[str, CatalogBarcodeItem]:
  """Индекс баркод → данные карточки WB для селлера."""
  try:
    cards = fetch_all_seller_cards(_get_token(seller))
  except WBApiError as exc:
    raise CatalogError(str(exc)) from exc
  index: dict[str, CatalogBarcodeItem] = {}
  for item in _parse_cards_to_items(cards):
    index[item.barcode] = item
  return index


def resolve_seller_warehouses(
  seller: Seller,
  warehouse_ids: list[int] | None,
) -> list[SellerWarehouse]:
  qs = SellerWarehouse.objects.filter(seller=seller)
  if warehouse_ids:
    qs = qs.filter(pk__in=warehouse_ids)
  warehouses = list(qs.order_by("name", "id"))
  if not warehouses:
    raise CatalogError("Выберите хотя бы один FBS-склад")
  return warehouses


def build_onboarding_preview(
  seller: Seller,
  *,
  catalog_mode: str = CATALOG_MODE_ALL,
  warehouse_ids: list[int] | None = None,
) -> dict:
  """Каталог WB + остатки по выбранным FBS-складам + план ячеек."""
  warehouses = resolve_seller_warehouses(seller, warehouse_ids)

  try:
    cards = fetch_all_seller_cards(_get_token(seller))
  except WBApiError as exc:
    raise CatalogError(str(exc)) from exc

  flat_items = _parse_cards_to_items(cards)
  if not flat_items:
    raise CatalogError("На WB не найдено карточек с баркодами")

  barcodes = [item.barcode for item in flat_items]
  try:
    stock_map = fetch_wb_stocks_for_warehouses(seller, warehouses, barcodes)
  except WBStockError as exc:
    raise CatalogError(str(exc)) from exc

  for item in flat_items:
    stock = stock_map.get(item.barcode, {})
    item.wb_stock_total = int(stock.get("total") or 0)
    item.wb_stock_by_warehouse = dict(stock.get("by_warehouse") or {})

  articles = _group_by_article(flat_items)

  if catalog_mode == CATALOG_MODE_WITH_STOCK:
    articles = [
      article
      for article in articles
      if any(item.wb_stock_total >= 1 for item in article.items)
    ]
    kept_barcodes = {item.barcode for article in articles for item in article.items}
    flat_items = [item for item in flat_items if item.barcode in kept_barcodes]

  existing_barcodes = set(
    Product.objects.filter(seller=seller).values_list("barcode", flat=True)
  )
  for item in flat_items:
    item.already_in_crm = item.barcode in existing_barcodes

  new_items = [item for item in flat_items if not item.already_in_crm]
  _assign_cell_numbers(new_items)

  return {
    "seller_id": seller.id,
    "catalog_mode": catalog_mode,
    "cards_count": len(cards),
    "barcodes_count": len(flat_items),
    "new_barcodes_count": len(new_items),
    "existing_barcodes_count": len(existing_barcodes),
    "filtered_articles_count": len(articles),
    "warehouses": [
      {
        "id": wh.id,
        "wb_warehouse_id": wh.wb_warehouse_id,
        "name": wh.name,
        "is_enabled": wh.is_enabled,
      }
      for wh in warehouses
    ],
    "articles": [_serialize_article(article) for article in articles],
    "items": [_serialize_item(item) for item in flat_items],
  }


def apply_exclusions_and_renumber(
  items: list[dict],
  *,
  exclude_barcodes: set[str] | None = None,
  exclude_nm_ids: set[int] | None = None,
) -> list[dict]:
  """Убрать баркоды/артикулы и перенумеровать ячейки для оставшихся новых."""
  exclude_barcodes = exclude_barcodes or set()
  exclude_nm_ids = exclude_nm_ids or set()

  result: list[dict] = []
  for item in items:
    barcode = item["barcode"]
    nm_id = int(item["wb_nm_id"])
    if barcode in exclude_barcodes or nm_id in exclude_nm_ids:
      item = {**item, "excluded": True, "cell_number": ""}
    else:
      item = {**item, "excluded": False}
    result.append(item)

  new_active = [
    item for item in result
    if not item.get("excluded") and not item.get("already_in_crm")
  ]
  for idx, item in enumerate(new_active, start=1):
    item["cell_number"] = str(idx)

  return result


def _serialize_item(item: CatalogBarcodeItem) -> dict:
  return {
    "barcode": item.barcode,
    "wb_nm_id": item.wb_nm_id,
    "vendor_code": item.vendor_code,
    "title": item.title,
    "tech_size": item.tech_size,
    "wb_size": item.wb_size,
    "size_label": item.tech_size or "—",
    "photo_url": item.photo_url,
    "requires_marking": item.requires_marking,
    "wb_stock_total": item.wb_stock_total,
    "wb_stock_by_warehouse": item.wb_stock_by_warehouse,
    "cell_number": item.cell_number,
    "already_in_crm": item.already_in_crm,
    "excluded": False,
  }


def _serialize_article(article: CatalogArticle) -> dict:
  return {
    "wb_nm_id": article.wb_nm_id,
    "vendor_code": article.vendor_code,
    "title": article.title,
    "photo_url": article.photo_url,
    "requires_marking": article.requires_marking,
    "items": [_serialize_item(item) for item in article.items],
  }
