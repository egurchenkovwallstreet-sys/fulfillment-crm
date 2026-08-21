"""Синхронизация названий и маркировки товаров из WB Content API."""
from __future__ import annotations

from dataclasses import dataclass, field

from apps.sellers.models import Seller
from apps.warehouse.models import Product
from apps.warehouse.services.marking_lookup import MarkingLookupError, lookup_marking_for_barcode


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


def refresh_product_from_wb(product: Product, seller: Seller) -> ProductRefreshResult:
  """Обновить название и requires_marking одного товара из WB."""
  try:
    marking = lookup_marking_for_barcode(seller, product.barcode)
  except MarkingLookupError as exc:
    return ProductRefreshResult(
      product_id=product.id,
      barcode=product.barcode,
      wb_found=False,
      warning=str(exc),
    )

  if not marking.wb_found:
    return ProductRefreshResult(
      product_id=product.id,
      barcode=product.barcode,
      wb_found=False,
      warning=marking.warning,
    )

  update_fields = ["requires_marking", "updated_at"]
  product.requires_marking = marking.requires_marking
  name_updated = False

  if marking.title:
    product.name = marking.title
    update_fields.append("name")
    name_updated = True

  product.save(update_fields=update_fields)
  return ProductRefreshResult(
    product_id=product.id,
    barcode=product.barcode,
    wb_found=True,
    name_updated=name_updated,
  )


def _is_token_error(warning: str) -> bool:
  lower = warning.lower()
  return "токен" in lower or "контент" in lower


def refresh_seller_products_from_wb(seller: Seller) -> SellerProductsRefreshResult:
  """Обновить все товары селлера из WB."""
  result = SellerProductsRefreshResult(seller_id=seller.id)

  for product in Product.objects.filter(seller=seller).order_by("id"):
    item = refresh_product_from_wb(product, seller)
    result.items.append(item)
    result.total += 1

    if item.warning and _is_token_error(item.warning):
      result.error = item.warning
      result.errors += 1
      break

    if item.wb_found:
      result.updated += 1
    else:
      result.not_found += 1
      if item.warning:
        result.errors += 1

  return result


def refresh_all_sellers_products_from_wb() -> dict:
  """Ежедневная синхронизация товаров всех активных селлеров."""
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
