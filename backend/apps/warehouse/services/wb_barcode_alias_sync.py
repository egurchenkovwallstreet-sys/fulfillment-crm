"""Синхронизация дополнительных баркодов WB (несколько skus[] на один chrtId)."""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field

from apps.integrations.marketplace import WB as MARKETPLACE_WB
from apps.sellers.models import Seller
from apps.warehouse.models import Product, ProductBarcodeAlias
from apps.warehouse.services.catalog_fetch import (
  CatalogError,
  build_seller_catalog_index,
  normalize_barcode,
)

logger = logging.getLogger(__name__)


@dataclass
class BarcodeAliasSyncResult:
  seller_id: int
  products_checked: int = 0
  aliases_added: int = 0
  aliases_removed: int = 0
  chrt_ids_updated: int = 0
  warnings: list[str] = field(default_factory=list)
  error: str = ""


def _barcodes_by_chrt_id(index: dict) -> dict[int, set[str]]:
  grouped: dict[int, set[str]] = defaultdict(set)
  for item in index.values():
    if not item.wb_chrt_id:
      continue
    code = normalize_barcode(item.barcode)
    if code:
      grouped[int(item.wb_chrt_id)].add(code)
  return grouped


def sync_wb_barcode_aliases_for_seller(seller: Seller) -> BarcodeAliasSyncResult:
  """
  Подтянуть из карточек WB все skus размера (chrtId) и привязать к одному Product.
  Основной баркод — product.barcode; остальные — ProductBarcodeAlias.
  """
  result = BarcodeAliasSyncResult(seller_id=seller.id)
  products = list(
    Product.objects.filter(seller=seller, marketplace=MARKETPLACE_WB).order_by("id")
  )
  result.products_checked = len(products)
  if not products:
    return result

  try:
    index = build_seller_catalog_index(seller)
  except CatalogError as exc:
    result.error = str(exc)
    return result

  by_chrt = _barcodes_by_chrt_id(index)

  for product in products:
    chrt_id = product.wb_chrt_id
    catalog_item = index.get(normalize_barcode(product.barcode))
    if catalog_item and catalog_item.wb_chrt_id:
      chrt_id = int(catalog_item.wb_chrt_id)
      if product.wb_chrt_id != chrt_id:
        product.wb_chrt_id = chrt_id
        product.save(update_fields=["wb_chrt_id", "updated_at"])
        result.chrt_ids_updated += 1

    if not chrt_id:
      continue

    all_skus = by_chrt.get(int(chrt_id), set())
    if len(all_skus) < 2:
      continue

    primary = normalize_barcode(product.barcode)
    expected_aliases = {sku for sku in all_skus if sku != primary}

    for sku in expected_aliases:
      if Product.objects.filter(
        seller=seller,
        marketplace=MARKETPLACE_WB,
        barcode=sku,
      ).exclude(pk=product.pk).exists():
        result.warnings.append(
          f"Баркод {sku} уже основной у другого товара — алиас для #{product.id} пропущен",
        )
        continue
      _, created = ProductBarcodeAlias.objects.get_or_create(
        product=product,
        barcode=sku,
      )
      if created:
        result.aliases_added += 1

  return result


def sync_wb_barcode_aliases_all_sellers() -> dict:
  sellers = Seller.objects.filter(is_active=True).exclude(wb_api_token_encrypted="")
  results: list[dict] = []
  errors: list[dict] = []
  for seller in sellers:
    sync_result = sync_wb_barcode_aliases_for_seller(seller)
    payload = {
      "seller_id": seller.id,
      "products_checked": sync_result.products_checked,
      "aliases_added": sync_result.aliases_added,
      "aliases_removed": sync_result.aliases_removed,
      "chrt_ids_updated": sync_result.chrt_ids_updated,
      "warnings": sync_result.warnings[:5],
    }
    if sync_result.error:
      errors.append({"seller_id": seller.id, "error": sync_result.error})
    results.append(payload)
    logger.info(
      "WB barcode aliases seller=%s added=%s removed=%s",
      seller.id,
      sync_result.aliases_added,
      sync_result.aliases_removed,
    )
  return {"results": results, "errors": errors}
