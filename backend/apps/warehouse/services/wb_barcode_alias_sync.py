"""Синхронизация дополнительных баркодов WB (несколько skus[] на один chrtId)."""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field

from apps.integrations.marketplace import WB as MARKETPLACE_WB
from apps.sellers.models import Seller
from apps.warehouse.models import Product, ProductBarcodeAlias
from apps.orders.models import Order
from apps.warehouse.services.catalog_fetch import (
  CatalogError,
  build_catalog_index_for_barcodes,
  build_seller_catalog_index,
  catalog_index_get,
  normalize_barcode,
  wb_ean_barcode_variants,
)
from apps.warehouse.services.product_lookup import (
  relink_orders_to_products_for_seller,
  resolve_product_by_barcode,
)

logger = logging.getLogger(__name__)


@dataclass
class BarcodeAliasSyncResult:
  seller_id: int
  products_checked: int = 0
  aliases_added: int = 0
  aliases_removed: int = 0
  chrt_ids_updated: int = 0
  orders_relinked: int = 0
  warnings: list[str] = field(default_factory=list)
  error: str = ""


def _expand_sku_variants(skus: set[str]) -> set[str]:
  expanded: set[str] = set()
  for sku in skus:
    for variant in wb_ean_barcode_variants(sku):
      if variant:
        expanded.add(variant)
  return expanded


def _barcodes_by_chrt_id(index: dict) -> dict[int, set[str]]:
  grouped: dict[int, set[str]] = defaultdict(set)
  seen_items: set[tuple[int, str]] = set()
  for item in index.values():
    if not item.wb_chrt_id:
      continue
    dedupe_key = (int(item.wb_chrt_id), normalize_barcode(item.barcode))
    if dedupe_key in seen_items:
      continue
    seen_items.add(dedupe_key)
    code = normalize_barcode(item.barcode)
    if code:
      grouped[int(item.wb_chrt_id)].add(code)
  return grouped


def _skus_for_chrt_id(index: dict, chrt_id: int) -> set[str]:
  skus: set[str] = set()
  seen: set[str] = set()
  for item in index.values():
    if not item.wb_chrt_id or int(item.wb_chrt_id) != int(chrt_id):
      continue
    code = normalize_barcode(item.barcode)
    if not code or code in seen:
      continue
    seen.add(code)
    skus.add(code)
  return skus


def _find_product_for_chrt(
  seller: Seller,
  chrt_id: int,
  skus: set[str],
) -> Product | None:
  for sku in skus:
    product = resolve_product_by_barcode(seller, MARKETPLACE_WB, sku)
    if product:
      return product
  product = Product.objects.filter(
    seller=seller,
    marketplace=MARKETPLACE_WB,
    wb_chrt_id=chrt_id,
  ).first()
  if product:
    return product
  for sku in skus:
    product = Product.objects.filter(
      seller=seller,
      marketplace=MARKETPLACE_WB,
      barcode=sku,
    ).first()
    if product:
      return product
  return None


def _backfill_product_chrt_ids(
  seller: Seller,
  index: dict,
  result: BarcodeAliasSyncResult,
) -> None:
  """Обновить wb_chrt_id у товаров CRM по основному баркоду в каталоге WB."""
  for product in Product.objects.filter(seller=seller, marketplace=MARKETPLACE_WB):
    catalog_item = catalog_index_get(index, product.barcode)
    if not catalog_item or not catalog_item.wb_chrt_id:
      continue
    chrt_id = int(catalog_item.wb_chrt_id)
    if product.wb_chrt_id != chrt_id:
      product.wb_chrt_id = chrt_id
      product.save(update_fields=["wb_chrt_id", "updated_at"])
      result.chrt_ids_updated += 1


def _sync_aliases_from_catalog_by_chrt(
  seller: Seller,
  by_chrt: dict[int, set[str]],
  result: BarcodeAliasSyncResult,
) -> None:
  """
  Для каждого размера WB (chrtId) с несколькими sku — все баркоды к одному Product CRM
  (та же ячейка, что у первого известного баркода).
  """
  for chrt_id, skus in by_chrt.items():
    if len(skus) < 2:
      continue
    product = _find_product_for_chrt(seller, chrt_id, skus)
    if not product:
      continue
    if not product.wb_chrt_id:
      product.wb_chrt_id = chrt_id
      product.save(update_fields=["wb_chrt_id", "updated_at"])
      result.chrt_ids_updated += 1
    _register_aliases_for_product(seller, product, skus, result)


def _register_aliases_for_product(
  seller: Seller,
  product: Product,
  skus: set[str],
  result: BarcodeAliasSyncResult,
) -> None:
  primary = normalize_barcode(product.barcode)
  primary_variants = set(wb_ean_barcode_variants(primary))
  for sku in _expand_sku_variants(skus):
    if sku in primary_variants:
      continue
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


def _sync_aliases_from_orphan_orders(
  seller: Seller,
  index: dict,
  by_chrt: dict[int, set[str]],
  result: BarcodeAliasSyncResult,
) -> None:
  """Заказы без product часто приходят со «вторым» sku — привязать к товару CRM."""
  orphan_codes = list(
    Order.objects.filter(seller=seller, product__isnull=True)
    .exclude(barcode="")
    .values_list("barcode", flat=True)
    .distinct()
  )
  if not orphan_codes:
    return

  missing = [
    normalize_barcode(code)
    for code in orphan_codes
    if normalize_barcode(code) and catalog_index_get(index, code) is None
  ]
  if missing:
    try:
      extra = build_catalog_index_for_barcodes(seller, missing)
      index.update(extra)
      for item in extra.values():
        if item.wb_chrt_id:
          by_chrt[int(item.wb_chrt_id)].add(normalize_barcode(item.barcode))
    except CatalogError as exc:
      result.warnings.append(f"Каталог WB для баркодов заказов: {exc}")
      return

  for raw in orphan_codes:
    code = normalize_barcode(raw)
    if not code:
      continue
    catalog_item = catalog_index_get(index, code)
    if not catalog_item or not catalog_item.wb_chrt_id:
      continue
    chrt_id = int(catalog_item.wb_chrt_id)
    skus = _skus_for_chrt_id(index, chrt_id) or set(by_chrt.get(chrt_id, set()))
    skus.add(code)
    product = _find_product_for_chrt(seller, chrt_id, skus)
    if not product:
      continue
    if not product.wb_chrt_id:
      product.wb_chrt_id = chrt_id
      product.save(update_fields=["wb_chrt_id", "updated_at"])
      result.chrt_ids_updated += 1
    _register_aliases_for_product(seller, product, skus, result)


def sync_wb_barcode_aliases_from_index(
  seller: Seller,
  index: dict,
  *,
  relink_orders: bool = True,
) -> BarcodeAliasSyncResult:
  """
  Синхронизация доп. баркодов по уже загруженному каталогу WB (без повторного запроса к API).
  """
  result = BarcodeAliasSyncResult(seller_id=seller.id)
  result.products_checked = Product.objects.filter(
    seller=seller,
    marketplace=MARKETPLACE_WB,
  ).count()
  by_chrt = _barcodes_by_chrt_id(index)
  _backfill_product_chrt_ids(seller, index, result)
  _sync_aliases_from_catalog_by_chrt(seller, by_chrt, result)
  _sync_aliases_from_orphan_orders(seller, index, by_chrt, result)
  _sync_aliases_from_linked_orders(seller, index, result)
  if relink_orders:
    result.orders_relinked = relink_orders_to_products_for_seller(seller)
  return result


def sync_wb_barcode_aliases_for_seller(seller: Seller) -> BarcodeAliasSyncResult:
  """
  Подтянуть из карточек WB все skus размера (chrtId) и привязать к одному Product.
  Основной баркод — product.barcode; остальные — ProductBarcodeAlias.
  """
  try:
    index = build_seller_catalog_index(seller, force_refresh=True)
  except CatalogError as exc:
    result = BarcodeAliasSyncResult(seller_id=seller.id)
    result.error = str(exc)
    return result

  return sync_wb_barcode_aliases_from_index(seller, index)


def _sync_aliases_from_linked_orders(
  seller: Seller,
  index: dict,
  result: BarcodeAliasSyncResult,
) -> None:
  """Заказы уже с product, но баркод заказа ещё не в паре SKU — дописать алиас."""
  from apps.warehouse.services.product_lookup import (
    product_scan_barcodes,
    sync_product_wb_barcodes,
  )

  orders = (
    Order.objects.filter(seller=seller, product__isnull=False)
    .exclude(barcode="")
    .select_related("product")
  )
  for order in orders.iterator():
    product = order.product
    if not product:
      continue
    scan_codes = product_scan_barcodes(product)
    order_code = normalize_barcode(order.barcode)
    if not order_code:
      continue
    if any(
      order_code == code or (
        order_code.isdigit()
        and code.isdigit()
        and (order_code.lstrip("0") or "0") == (code.lstrip("0") or "0")
      )
      for code in scan_codes
    ):
      continue
    added = sync_product_wb_barcodes(
      seller,
      product,
      catalog_index=index,
      extra_barcodes={order.barcode},
    )
    result.aliases_added += added


def sync_linked_order_barcodes_for_seller(seller: Seller) -> int:
  """Дописать вторые баркоды WB к товарам по уже привязанным заказам (без force refresh)."""
  try:
    index = build_seller_catalog_index(seller)
  except CatalogError:
    index = {}
  result = BarcodeAliasSyncResult(seller_id=seller.id)
  _sync_aliases_from_linked_orders(seller, index, result)
  return result.aliases_added


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
      "orders_relinked": sync_result.orders_relinked,
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
