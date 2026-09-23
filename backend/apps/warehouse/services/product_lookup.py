"""Поиск товара CRM по основному и дополнительным баркодам WB."""
from __future__ import annotations

from django.utils import timezone

from apps.integrations.marketplace import WB as MARKETPLACE_WB
from apps.integrations.marketplace import normalize_marketplace
from apps.sellers.models import Seller
from apps.warehouse.models import Product, ProductBarcodeAlias
from apps.warehouse.services.catalog_fetch import (
  CatalogError,
  barcode_lookup_variants,
  build_seller_catalog_index,
  catalog_index_get,
  normalize_barcode,
)


def ensure_barcode_alias(product: Product, barcode: str) -> bool:
  """Записать второй sku WB как алиас (если это не основной баркод)."""
  code = normalize_barcode(barcode)
  if not code:
    return False
  primary_variants = {
    normalize_barcode(variant)
    for variant in barcode_lookup_variants(product.barcode, product.marketplace)
  }
  if code in primary_variants:
    return False
  if Product.objects.filter(
    seller=product.seller,
    marketplace=product.marketplace,
    barcode=code,
  ).exclude(pk=product.pk).exists():
    return False
  _, created = ProductBarcodeAlias.objects.get_or_create(
    product=product,
    barcode=code,
  )
  return created


def build_wb_chrt_product_map(
  seller: Seller,
  *,
  catalog_index: dict | None = None,
) -> dict[int, Product]:
  """chrtId WB → товар CRM (один размер = один Product, любой sku)."""
  index = catalog_index
  if index is None:
    try:
      index = build_seller_catalog_index(seller)
    except CatalogError:
      index = {}

  chrt_map: dict[int, Product] = {}
  products = Product.objects.filter(
    seller=seller,
    marketplace=MARKETPLACE_WB,
  ).select_related("cell")

  chrt_ids_to_backfill: dict[int, int] = {}
  for product in products:
    if product.wb_chrt_id:
      chrt_map.setdefault(int(product.wb_chrt_id), product)
    cat = catalog_index_get(index, product.barcode)
    if cat and cat.wb_chrt_id:
      chrt_id = int(cat.wb_chrt_id)
      chrt_map.setdefault(chrt_id, product)
      if not product.wb_chrt_id:
        chrt_ids_to_backfill[product.id] = chrt_id

  now = timezone.now()
  for product_id, chrt_id in chrt_ids_to_backfill.items():
    Product.objects.filter(pk=product_id, wb_chrt_id__isnull=True).update(
      wb_chrt_id=chrt_id,
      updated_at=now,
    )

  return chrt_map


def _resolve_by_wb_chrt_id(
  seller: Seller,
  barcode: str,
  *,
  catalog_index: dict | None,
  chrt_product_map: dict[int, Product] | None,
  select_cell: bool,
  register_alias: bool,
) -> Product | None:
  index = catalog_index
  if index is None:
    try:
      index = build_seller_catalog_index(seller)
    except CatalogError:
      return None

  cat = catalog_index_get(index, barcode)
  if not cat or not cat.wb_chrt_id:
    return None

  chrt_id = int(cat.wb_chrt_id)
  chrt_map = chrt_product_map
  if chrt_map is None:
    chrt_map = build_wb_chrt_product_map(seller, catalog_index=index)

  product = chrt_map.get(chrt_id)
  if not product:
    return None

  if select_cell and product.cell_id is None:
    product = Product.objects.select_related("cell").filter(pk=product.pk).first()
  if product and register_alias:
    ensure_barcode_alias(product, barcode)
  return product


def resolve_product_by_barcode(
  seller: Seller,
  marketplace: str,
  barcode: str,
  *,
  select_cell: bool = False,
  catalog_index: dict | None = None,
  chrt_product_map: dict[int, Product] | None = None,
  register_alias: bool = False,
) -> Product | None:
  """Найти товар: основной/алиас баркод → EAN-варианты → chrtId WB."""
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

  if mp == MARKETPLACE_WB:
    return _resolve_by_wb_chrt_id(
      seller,
      barcode,
      catalog_index=catalog_index,
      chrt_product_map=chrt_product_map,
      select_cell=select_cell,
      register_alias=register_alias,
    )
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


def product_alternate_barcodes(product: Product) -> list[str]:
  """Доп. баркоды SKU (без основного product.barcode)."""
  primary_variants = {
    normalize_barcode(variant)
    for variant in barcode_lookup_variants(product.barcode, product.marketplace)
  }
  primary_variants.discard("")
  return [
    code
    for code in sorted(product_scan_barcodes(product))
    if code and code not in primary_variants
  ]


def sync_product_wb_barcodes(
  seller: Seller,
  product: Product,
  *,
  catalog_index: dict | None = None,
  extra_barcodes: set[str] | None = None,
) -> int:
  """
  Записать в CRM все skus размера WB (chrtId) + доп. баркоды заказов как алиасы.
  Основной баркод ячейки — product.barcode; второй sku WB — ProductBarcodeAlias.
  """
  from apps.warehouse.services.catalog_fetch import (
    CatalogError,
    build_seller_catalog_index,
    catalog_index_get,
  )
  from apps.warehouse.services.wb_barcode_alias_sync import (
    _register_aliases_for_product,
    _skus_for_chrt_id,
    BarcodeAliasSyncResult,
  )

  if normalize_marketplace(product.marketplace) != MARKETPLACE_WB:
    return 0

  index = catalog_index
  if index is None:
    try:
      index = build_seller_catalog_index(seller)
    except CatalogError:
      index = {}

  chrt_id = product.wb_chrt_id
  catalog_item = catalog_index_get(index, product.barcode)
  if catalog_item and catalog_item.wb_chrt_id:
    chrt_id = int(catalog_item.wb_chrt_id)
    if product.wb_chrt_id != chrt_id:
      product.wb_chrt_id = chrt_id
      product.save(update_fields=["wb_chrt_id", "updated_at"])

  skus: set[str] = set()
  if chrt_id:
    skus.update(_skus_for_chrt_id(index, int(chrt_id)))
  if extra_barcodes:
    for raw in extra_barcodes:
      code = normalize_barcode(raw)
      if code:
        skus.add(code)

  if not skus:
    return 0

  result = BarcodeAliasSyncResult(seller_id=seller.id)
  _register_aliases_for_product(seller, product, skus, result)
  return result.aliases_added


def products_by_barcodes(
  seller: Seller,
  barcodes: set[str],
  *,
  marketplace: str,
  catalog_index: dict | None = None,
  chrt_product_map: dict[int, Product] | None = None,
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
    if code in result:
      continue
    if mp == MARKETPLACE_WB:
      product = _resolve_by_wb_chrt_id(
        seller,
        code,
        catalog_index=catalog_index,
        chrt_product_map=chrt_product_map,
        select_cell=True,
        register_alias=True,
      )
      if product:
        sync_product_wb_barcodes(
          seller,
          product,
          catalog_index=catalog_index,
          extra_barcodes={code},
        )
        result[code] = product
  return result


def relink_orders_to_products_for_seller(seller: Seller) -> int:
  """Проставить order.product для заказов с «вторым» баркодом (chrtId/алиас)."""
  from apps.orders.models import Order

  try:
    catalog_index = build_seller_catalog_index(seller)
    chrt_map = build_wb_chrt_product_map(seller, catalog_index=catalog_index)
  except CatalogError:
    catalog_index = None
    chrt_map = None

  updated = 0
  now = timezone.now()
  orders = Order.objects.filter(seller=seller, product__isnull=True).exclude(barcode="")
  for order in orders.only("id", "barcode").iterator():
    product = resolve_product_by_barcode(
      seller,
      MARKETPLACE_WB,
      order.barcode,
      catalog_index=catalog_index,
      chrt_product_map=chrt_map,
      register_alias=True,
    )
    if not product:
      continue
    sync_product_wb_barcodes(
      seller,
      product,
      catalog_index=catalog_index,
      extra_barcodes={order.barcode},
    )
    Order.objects.filter(pk=order.pk).update(product=product, updated_at=now)
    updated += 1
  return updated

