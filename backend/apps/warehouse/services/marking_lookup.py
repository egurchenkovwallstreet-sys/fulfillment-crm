"""Определение требования маркировки ЧЗ по карточке WB."""
from __future__ import annotations

from dataclasses import dataclass

from apps.integrations.wb_content import lookup_need_kiz
from apps.integrations.wb_crypto import TokenCryptoError, decrypt_token
from apps.sellers.models import Seller
from apps.warehouse.models import Product


@dataclass
class MarkingLookupResult:
  requires_marking: bool
  wb_found: bool
  title: str = ""
  warning: str = ""


class MarkingLookupError(Exception):
  pass


def _get_token(seller: Seller) -> str:
  if not seller.wb_api_token_encrypted:
    raise MarkingLookupError(
      f"У селлера «{seller.company_name}» не задан токен WB — "
      "невозможно проверить маркировку автоматически"
    )
  try:
    return decrypt_token(seller.wb_api_token_encrypted)
  except TokenCryptoError as exc:
    raise MarkingLookupError(str(exc)) from exc


def lookup_marking_for_barcode(seller: Seller, barcode: str) -> MarkingLookupResult:
  """Запрос needKiz в карточке WB по баркоду."""
  token = _get_token(seller)
  info = lookup_need_kiz(token, barcode)

  if info.error and not info.found:
    return MarkingLookupResult(
      requires_marking=False,
      wb_found=False,
      warning=info.error,
    )

  return MarkingLookupResult(
    requires_marking=info.need_kiz,
    wb_found=info.found,
    title=info.title,
  )


def resolve_product_requires_marking(product: Product | None, barcode: str, seller: Seller) -> bool:
  """Нужна ли маркировка для товара/баркода."""
  if product and product.requires_marking:
    return True
  fallback = Product.objects.filter(seller=seller, barcode=barcode).first()
  if fallback:
    return fallback.requires_marking
  return False


def refresh_product_marking(product: Product, seller: Seller) -> MarkingLookupResult:
  """Обновить название и requires_marking у товара из WB."""
  result = lookup_marking_for_barcode(seller, product.barcode)
  if result.wb_found:
    update_fields = ["requires_marking", "updated_at"]
    product.requires_marking = result.requires_marking
    if result.title:
      product.name = result.title
      update_fields.append("name")
    product.save(update_fields=update_fields)
  return result
