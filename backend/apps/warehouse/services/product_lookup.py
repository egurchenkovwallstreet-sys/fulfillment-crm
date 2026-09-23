"""Поиск товара CRM по основному и дополнительным баркодам WB."""
from __future__ import annotations

from django.utils import timezone

from apps.integrations.marketplace import WB as MARKETPLACE_WB
from apps.integrations.marketplace import normalize_marketplace
from apps.sellers.models import Seller
from apps.warehouse.models import Product, ProductBarcodeAlias
from apps.warehouse.services.catalog_fetch import barcode_lookup_variants, normalize_barcode


def resolve_product_by_barcode(
  seller: Seller,
  marketplace: str,
  barcode: str,
  *,
  select_cell: bool = False,
) -> Product | None:
  """Найти товар по основному или альтернативному баркоду."""
  mp = normalize_marketplace(marketplace)
  for variant in barcode_lookup_variants(barcode, mp):
    code = normalize_barcode(variant)
    if not code:
      continue
    qs = Product.objects.filter(seller=seller, marketplace=mp, barcode=code)
    if select_cell:
      qs = qs.select_related("cell")
    product = qs.first()
    if product:
      return product
    alias_qs = ProductBarcodeAlias.objects.filter(
      product__seller=seller,
      product__marketplace=mp,
      barcode=code,
    ).select_related("product")
    if select_cell:
      alias_qs = alias_qs.select_related("product__cell")
    alias = alias_qs.first()
    if alias:
      return alias.product
  return None


def product_scan_barcodes(product: Product) -> set[str]:
  """Все баркоды товара для сопоставления со сканом (основной + алиасы)."""
  codes: set[str] = set()
  primary = normalize_barcode(product.barcode)
  if primary:
    codes.add(primary)
  for raw in ProductBarcodeAlias.objects.filter(product=product).values_list("barcode", flat=True):
    code = normalize_barcode(raw)
    if code:
      codes.add(code)
  return codes


def products_by_barcodes(
  seller: Seller,
  barcodes: set[str],
  *,
  marketplace: str,
) -> dict[str, Product]:
  """Словарь баркод → товар (основные и альтернативные коды)."""
  mp = normalize_marketplace(marketplace)
  requested = {normalize_barcode(code) for code in barcodes if normalize_barcode(code)}
  if not requested:
    return {}

  lookup_codes: set[str] = set()
  for code in requested:
    for variant in barcode_lookup_variants(code, mp):
      lookup_codes.add(normalize_barcode(variant))

  by_code: dict[str, Product] = {}
  products = (
    Product.objects.filter(seller=seller, marketplace=mp, barcode__in=lookup_codes)
    .select_related("cell")
  )
  for product in products:
    by_code[product.barcode] = product

  aliases = (
    ProductBarcodeAlias.objects.filter(
      product__seller=seller,
      product__marketplace=mp,
      barcode__in=lookup_codes,
    )
    .select_related("product", "product__cell")
  )
  for alias in aliases:
    by_code.setdefault(alias.barcode, alias.product)

  result: dict[str, Product] = {}
  for code in requested:
    for variant in barcode_lookup_variants(code, mp):
      product = by_code.get(normalize_barcode(variant))
      if product:
        result[code] = product
        break
  return result


def relink_orders_to_products_for_seller(seller: Seller) -> int:
  """Проставить order.product для заказов с «вторым» баркодом (через алиас)."""
  from apps.orders.models import Order

  updated = 0
  now = timezone.now()
  orders = Order.objects.filter(seller=seller, product__isnull=True).exclude(barcode="")
  for order in orders.only("id", "barcode").iterator():
    product = resolve_product_by_barcode(seller, MARKETPLACE_WB, order.barcode)
    if not product:
      continue
    Order.objects.filter(pk=order.pk).update(product=product, updated_at=now)
    updated += 1
  return updated
