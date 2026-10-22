"""Поиск ячейки и клиента по скану баркода (режим «Сортировка», только WB)."""
from __future__ import annotations

from dataclasses import dataclass

from django.contrib.auth.models import AbstractBaseUser

from apps.accounts.tenant import sellers_for_user
from apps.integrations.marketplace import WB, filter_sellers_qs
from apps.warehouse.models import Product, ProductBarcodeAlias
from apps.warehouse.services.catalog_fetch import barcode_lookup_variants, normalize_barcode
from apps.warehouse.services.product_lookup import resolve_product_by_barcode


@dataclass(frozen=True)
class SortLookupResult:
  found: bool
  company_name: str = ""
  cell_number: str = ""
  barcode: str = ""
  detail: str = ""


def _products_for_code(seller_ids: list[int], code: str) -> list[Product]:
  if not code:
    return []
  return list(
    Product.objects.filter(
      seller_id__in=seller_ids,
      marketplace=WB,
      barcode=code,
    ).select_related("cell", "seller")
  )


def _product_from_alias(seller_ids: list[int], code: str) -> Product | None:
  alias = (
    ProductBarcodeAlias.objects.filter(
      product__seller_id__in=seller_ids,
      product__marketplace=WB,
      barcode=code,
    )
    .select_related("product", "product__cell", "product__seller")
    .first()
  )
  return alias.product if alias else None


def lookup_sort_wb(user: AbstractBaseUser, barcode: str) -> SortLookupResult:
  raw = (barcode or "").strip()
  if len(raw) < 4:
    return SortLookupResult(found=False, detail="Слишком короткий баркод")

  sellers_qs = filter_sellers_qs(
    sellers_for_user(user).filter(is_active=True),
    WB,
  )
  seller_ids = list(sellers_qs.values_list("id", flat=True))
  if not seller_ids:
    return SortLookupResult(found=False, detail="Нет активных клиентов WB")

  matched: Product | None = None
  for variant in barcode_lookup_variants(raw, WB):
    code = normalize_barcode(variant)
    if not code:
      continue
    direct_list = _products_for_code(seller_ids, code)
    if len({p.seller_id for p in direct_list}) > 1:
      return SortLookupResult(
        found=False,
        detail="Баркод найден у нескольких клиентов — уточните у администратора",
      )
    if len(direct_list) == 1:
      matched = direct_list[0]
      break
    alias_product = _product_from_alias(seller_ids, code)
    if alias_product:
      if matched and matched.pk != alias_product.pk:
        return SortLookupResult(
          found=False,
          detail="Баркод найден у нескольких клиентов — уточните у администратора",
        )
      matched = alias_product

  if matched:
    cell_number = matched.cell.number if matched.cell_id else ""
    if not cell_number:
      return SortLookupResult(
        found=False,
        barcode=normalize_barcode(raw) or raw,
        detail="Товар без ячейки — назначьте ячейку на складе",
      )
    return SortLookupResult(
      found=True,
      company_name=matched.seller.company_name,
      cell_number=cell_number,
      barcode=normalize_barcode(raw) or raw,
    )

  for seller in sellers_qs.order_by("company_name"):
    product = resolve_product_by_barcode(
      seller,
      WB,
      raw,
      select_cell=True,
      register_alias=False,
    )
    if not product:
      continue
    if matched and matched.pk != product.pk:
      return SortLookupResult(
        found=False,
        detail="Баркод найден у нескольких клиентов — уточните у администратора",
      )
    matched = product

  if not matched:
    return SortLookupResult(
      found=False,
      barcode=normalize_barcode(raw) or raw,
      detail="Товар не найден в CRM",
    )

  cell_number = matched.cell.number if matched.cell_id else ""
  if not cell_number:
    return SortLookupResult(
      found=False,
      barcode=normalize_barcode(raw) or raw,
      detail="Товар без ячейки — назначьте ячейку на складе",
    )
  return SortLookupResult(
    found=True,
    company_name=matched.seller.company_name,
    cell_number=cell_number,
    barcode=normalize_barcode(raw) or raw,
  )
