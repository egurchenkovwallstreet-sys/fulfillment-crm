"""Группы артикул+цвет для приёмки с формированием ячеек."""
from __future__ import annotations

from apps.integrations.marketplace import OZON, WB, normalize_marketplace
from apps.integrations.wb_content import fetch_all_seller_cards
from apps.sellers.models import Seller
from apps.warehouse.services.catalog_fetch import (
  CatalogBarcodeItem,
  CatalogError,
  _get_token,
  normalize_barcode,
  parse_wb_card_to_items,
)
from apps.warehouse.services.catalog_fetch_ozon import fetch_ozon_group_by_barcode, ozon_group_key
from apps.warehouse.services.size_sort import size_sort_key


def group_key_for_item(
  marketplace: str,
  item: CatalogBarcodeItem,
  raw_card: dict | None = None,
) -> str:
  mp = normalize_marketplace(marketplace)
  if mp == OZON:
    return ozon_group_key(item, raw_card)
  return f"wb:{item.wb_nm_id}"


def items_in_same_group(
  marketplace: str,
  all_items: list[CatalogBarcodeItem],
  anchor: CatalogBarcodeItem,
) -> list[CatalogBarcodeItem]:
  key = group_key_for_item(marketplace, anchor)
  grouped = [
    item
    for item in all_items
    if group_key_for_item(marketplace, item) == key
  ]
  grouped.sort(key=lambda item: (size_sort_key(item.tech_size, item.wb_size), item.barcode))
  return grouped


def find_wb_group_by_barcode(seller: Seller, barcode: str) -> tuple[CatalogBarcodeItem, list[CatalogBarcodeItem]]:
  barcode = normalize_barcode(barcode)
  if not barcode:
    raise CatalogError("Пустой баркод")
  try:
    cards = fetch_all_seller_cards(_get_token(seller))
  except Exception as exc:
    raise CatalogError(str(exc)) from exc

  for card in cards:
    for size in card.get("sizes") or []:
      skus = [normalize_barcode(str(sku)) for sku in (size.get("skus") or [])]
      if barcode in skus:
        items = parse_wb_card_to_items(card)
        anchor = next((item for item in items if item.barcode == barcode), None)
        if anchor:
          return anchor, items
  raise CatalogError("Баркод не найден в каталоге WB")


def find_ozon_group_by_barcode(
  seller: Seller,
  barcode: str,
) -> tuple[CatalogBarcodeItem, list[CatalogBarcodeItem], dict]:
  return fetch_ozon_group_by_barcode(seller, barcode)


def find_group_by_barcode(
  seller: Seller,
  marketplace: str,
  barcode: str,
) -> tuple[CatalogBarcodeItem, list[CatalogBarcodeItem], dict]:
  mp = normalize_marketplace(marketplace)
  if mp == OZON:
    return find_ozon_group_by_barcode(seller, barcode)
  anchor, items = find_wb_group_by_barcode(seller, barcode)
  group_key = f"wb:{anchor.wb_nm_id}"
  return anchor, items, {
    "article_label": anchor.vendor_code or str(anchor.wb_nm_id),
    "group_size": len(items),
    "group_key": group_key,
  }


def serialize_group_item(
  item: CatalogBarcodeItem,
  *,
  cell_number: str = "",
  quantity: int = 0,
  already_in_crm: bool = False,
  excluded: bool = False,
) -> dict:
  return {
    "barcode": item.barcode,
    "wb_nm_id": item.wb_nm_id,
    "vendor_code": item.vendor_code,
    "article_label": item.vendor_code or str(item.wb_nm_id),
    "title": item.title,
    "tech_size": item.tech_size,
    "wb_size": item.wb_size,
    "size_label": item.tech_size or item.wb_size or "—",
    "color_label": item.color_label,
    "photo_url": item.photo_url,
    "requires_marking": item.requires_marking,
    "cell_number": cell_number,
    "quantity": quantity,
    "already_in_crm": already_in_crm,
    "excluded": excluded,
  }


def serialize_group_preview(
  marketplace: str,
  anchor: CatalogBarcodeItem,
  items: list[CatalogBarcodeItem],
  *,
  scanned_barcode: str,
  scanned_quantity: int,
  cell_numbers: dict[str, str],
  existing_barcodes: set[str],
  article_label: str = "",
) -> dict:
  label = article_label or anchor.vendor_code or str(anchor.wb_nm_id)
  return {
    "group_key": group_key_for_item(marketplace, anchor),
    "article_id": anchor.wb_nm_id,
    "article_label": label,
    "vendor_code": anchor.vendor_code,
    "title": anchor.title,
    "color_label": anchor.color_label or "—",
    "group_size": len(items),
    "photo_url": anchor.photo_url,
    "scanned_barcode": scanned_barcode,
    "scanned_quantity": scanned_quantity,
    "items": [
      serialize_group_item(
        item,
        cell_number=cell_numbers.get(item.barcode, ""),
        quantity=scanned_quantity if item.barcode == scanned_barcode else 0,
        already_in_crm=item.barcode in existing_barcodes,
        excluded=False,
      )
      for item in items
    ],
  }
