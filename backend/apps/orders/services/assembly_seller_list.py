"""Список селлеров на странице «Сборка FBS» — лёгкий кеш счётчиков (не трогает WB API)."""
from __future__ import annotations

from django.core.cache import cache

from apps.accounts.tenant import get_user_fulfillment, sellers_for_user
from apps.integrations.marketplace import OZON, filter_sellers_qs
from apps.orders.services.assembly import get_seller_stage_counts, get_seller_wb_tab_counts

ASSEMBLY_SELLERS_CACHE_TTL = 55


def _assembly_sellers_cache_key(user, marketplace: str) -> str:
  fulfillment = get_user_fulfillment(user)
  ff_id = fulfillment.id if fulfillment else 0
  return f"assembly_sellers:v1:ff{ff_id}:mp{marketplace}"


def build_assembly_seller_list(user, marketplace: str) -> list[dict]:
  """Счётчики по селлерам из CRM (без запросов в WB)."""
  sellers = filter_sellers_qs(
    sellers_for_user(user).filter(is_active=True),
    marketplace,
  ).order_by("company_name")

  payload: list[dict] = []
  for seller in sellers:
    if marketplace == OZON:
      from apps.orders.services.ozon_counts import get_seller_ozon_tab_counts

      tab_counts = get_seller_ozon_tab_counts(seller, assembly_only=True)
      stage_counts = {
        "assembled": 0,
        "label_printed": 0,
        "marked": 0,
        "in_supply": 0,
        "shipped": 0,
        "cancelled": 0,
      }
    else:
      stage_counts = get_seller_stage_counts(seller, assembly_only=True)
      tab_counts = get_seller_wb_tab_counts(seller, assembly_only=True)

    total_active = tab_counts["new"] + tab_counts["in_picking"] + tab_counts["in_delivery"]
    payload.append({
      "id": seller.id,
      "company_name": seller.company_name,
      **stage_counts,
      "new": tab_counts["new"],
      "in_picking": tab_counts["in_picking"],
      "in_delivery": tab_counts["in_delivery"],
      "total_active": total_active,
      "marketplace": marketplace,
      "has_ozon_api": bool(seller.ozon_client_id and seller.ozon_api_key_encrypted),
    })
  return payload


def get_assembly_seller_list(user, marketplace: str, *, refresh: bool = False) -> list[dict]:
  """Вернуть список селлеров; по умолчанию из Redis-кеша (TTL ~1 мин)."""
  cache_key = _assembly_sellers_cache_key(user, marketplace)
  if not refresh:
    cached = cache.get(cache_key)
    if cached is not None:
      return cached

  payload = build_assembly_seller_list(user, marketplace)
  cache.set(cache_key, payload, ASSEMBLY_SELLERS_CACHE_TTL)
  return payload


def invalidate_assembly_seller_list_cache(*, fulfillment_id: int | None = None) -> None:
  """Сбросить кеш списка (после ручного sync — опционально)."""
  if fulfillment_id is None:
    return
  for mp in ("wb", "ozon"):
    cache.delete(_assembly_sellers_cache_key_for_ff(fulfillment_id, mp))


def _assembly_sellers_cache_key_for_ff(fulfillment_id: int, marketplace: str) -> str:
  return f"assembly_sellers:v1:ff{fulfillment_id}:mp{marketplace}"
