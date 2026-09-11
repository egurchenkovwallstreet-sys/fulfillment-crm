"""Синхронизация карточек товаров из WB/Ozon в CRM."""
from __future__ import annotations

from dataclasses import dataclass, field

from apps.integrations.marketplace import OZON, WB
from apps.sellers.models import Seller
from apps.warehouse.models import Product
from apps.warehouse.services.catalog_fetch import (
  CatalogError,
  barcode_lookup_variants,
  build_seller_catalog_index,
)
from apps.warehouse.services.product_catalog import (
  apply_catalog_item_to_product,
  build_ozon_catalog_index,
)


@dataclass
class ProductRefreshResult:
  product_id: int
  barcode: str
  wb_found: bool
  name_updated: bool = False
  warning: str = ""


@dataclass
class SellerProductsRefreshResult:
  seller_id: int
  total: int = 0
  updated: int = 0
  not_found: int = 0
  errors: int = 0
  items: list[ProductRefreshResult] = field(default_factory=list)
  error: str = ""


def _lookup_in_index(index: dict, barcode: str, marketplace: str):
  for variant in barcode_lookup_variants(barcode, marketplace):
    item = index.get(variant)
    if item:
      return item
  return None


def _refresh_product_from_index(product: Product, index: dict, marketplace: str) -> ProductRefreshResult:
  item = _lookup_in_index(index, product.barcode, marketplace)
  if not item:
    return ProductRefreshResult(
      product_id=product.id,
      barcode=product.barcode,
      wb_found=False,
    )

  changed = apply_catalog_item_to_product(product, item)
  name_updated = "name" in changed
  if changed:
    product.save(update_fields=[*changed, "updated_at"])

  return ProductRefreshResult(
    product_id=product.id,
    barcode=product.barcode,
    wb_found=True,
    name_updated=name_updated,
  )


def refresh_seller_products_from_wb(seller: Seller) -> SellerProductsRefreshResult:
  """Обновить все товары селлера из каталога МП (фото, размеры, название)."""
  result = SellerProductsRefreshResult(seller_id=seller.id)
  products = list(Product.objects.filter(seller=seller).order_by("id"))
  result.total = len(products)
  if not products:
    return result

  wb_products = [p for p in products if p.marketplace == WB]
  ozon_products = [p for p in products if p.marketplace == OZON]

  wb_index: dict | None = None
  ozon_index: dict | None = None

  if wb_products:
    try:
      wb_index = build_seller_catalog_index(seller)
    except CatalogError as exc:
      result.error = str(exc)
      result.errors = len(wb_products)
      return result

  if ozon_products and seller.ozon_enabled:
    try:
      ozon_index = build_ozon_catalog_index(seller)
    except CatalogError as exc:
      if not result.error:
        result.error = str(exc)
      result.errors += len(ozon_products)
      ozon_index = None

  for product in products:
    if product.marketplace == WB:
      if wb_index is None:
        continue
      item_result = _refresh_product_from_index(product, wb_index, WB)
    elif product.marketplace == OZON:
      if ozon_index is None:
        result.not_found += 1
        continue
      item_result = _refresh_product_from_index(product, ozon_index, OZON)
    else:
      result.not_found += 1
      continue

    result.items.append(item_result)
    if item_result.wb_found:
      result.updated += 1
    else:
      result.not_found += 1

  return result


def refresh_all_sellers_products_from_wb() -> dict:
  """Ежедневная синхронизация карточек всех активных селлеров."""
  results: list[dict] = []
  errors: list[dict] = []

  for seller in Seller.objects.filter(is_active=True):
    sync_result = refresh_seller_products_from_wb(seller)
    payload = {
      "seller_id": seller.id,
      "total": sync_result.total,
      "updated": sync_result.updated,
      "not_found": sync_result.not_found,
    }
    if sync_result.error:
      errors.append({"seller_id": seller.id, "error": sync_result.error, **payload})
    else:
      results.append(payload)

  return {"results": results, "errors": errors}
