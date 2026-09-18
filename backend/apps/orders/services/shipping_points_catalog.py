"""Пункты отгрузки WB: только ответ API, СЦ и склады (без ПВЗ/ППТ и без подмены ID)."""
from __future__ import annotations

import logging
import time

from django.core.cache import cache
from django.utils import timezone

from apps.integrations.wb_client import WBApiError
from apps.orders.services.moscow_region_cities import MOSCOW_REGION_50KM_CITIES
from apps.sellers.models import Seller

logger = logging.getLogger(__name__)

SC_LIST_CARGO_TYPES: tuple[int, ...] = (1, 3)
SHIPPING_POINTS_CACHE_VERSION = "v12"
SHIPPING_PREFETCH_NEAR_DONE_THRESHOLD = 10
SHIPPING_PREFETCH_DEBOUNCE_SEC = 300
SHIPPING_SUPPLY_PREFETCH_FLAG_TTL = 3600
ALL_SC_SHIPPING_CACHE_TTL = 3600
SUPPLY_CARGO_CACHE_TTL = 86400


def _normalize_text(value: object) -> str:
  return str(value or "").strip().lower().replace("ё", "е")


def _point_haystack(point: dict) -> str:
  return " ".join(
    _normalize_text(point.get(key))
    for key in ("name", "address", "city")
  )


def _is_sc_office_type(point: dict) -> bool:
  return _normalize_text(point.get("officeType")) in ("sc", "sw")


def _filter_sc_sw_points(points: list[dict]) -> list[dict]:
  """Только СЦ и склады WB — без ПВЗ, ППТ и officeType=pp."""
  return [
    point for point in points
    if isinstance(point, dict) and point.get("id") is not None and _is_sc_office_type(point)
  ]


def _point_supports_any_cargo(point: dict, cargo_types: tuple[int, ...]) -> bool:
  supported = point.get("cargoTypes") or []
  if not supported:
    return True
  allowed = {int(item) for item in supported}
  return any(int(cargo_type) in allowed for cargo_type in cargo_types)


def _union_shipping_point(left: dict, right: dict) -> dict:
  merged = dict(left)
  cargo_types: set[int] = set()
  for source in (left, right):
    for item in source.get("cargoTypes") or []:
      cargo_types.add(int(item))
  if cargo_types:
    merged["cargoTypes"] = sorted(cargo_types)
  for key in ("name", "address", "city", "officeType"):
    if not merged.get(key) and right.get(key):
      merged[key] = right[key]
  return merged


def _fetch_city_shipping_points(
  client,
  city: str,
  cargo_types: tuple[int, ...],
) -> list[dict]:
  merged: dict[int, dict] = {}
  for cargo_type in cargo_types:
    try:
      batch = client.fetch_shipping_points(city, cargo_type)
    except WBApiError:
      continue
    for point in batch:
      if not isinstance(point, dict) or point.get("id") is None:
        continue
      if not _is_sc_office_type(point):
        continue
      point_id = int(point["id"])
      if point_id in merged:
        merged[point_id] = _union_shipping_point(merged[point_id], point)
      else:
        merged[point_id] = dict(point)
  return list(merged.values())


def _sort_sc_points(points: list[dict]) -> list[dict]:
  return sorted(
    points,
    key=lambda point: (
      _normalize_text(point.get("city")),
      _normalize_text(point.get("name")),
      _normalize_text(point.get("address")),
    ),
  )


def _shipping_point_zone_label(point: dict) -> str:
  haystack = _point_haystack(point)
  if any(token in haystack for token in ("коледино", "софьино", "домодедово", "видное")):
    return "Юг"
  if any(token in haystack for token in ("электросталь", "ногинск", "балаших", "жуковск")):
    return "Восток"
  if any(token in haystack for token in ("химки", "красногорск", "одинц", "внуков", "рассказов")):
    return "Запад"
  if any(token in haystack for token in ("мытищ", "пушкино", "щелков", "королев", "вешк", "вёшк", "липкин")):
    return "Север"
  return ""


def serialize_shipping_point_for_api(point: dict) -> dict:
  cargo_types = point.get("cargoTypes") or []
  return {
    "id": int(point["id"]),
    "name": str(point.get("name") or ""),
    "address": str(point.get("address") or ""),
    "city": str(point.get("city") or ""),
    "officeType": str(point.get("officeType") or ""),
    "cargoTypes": [int(item) for item in cargo_types],
    "zone_label": _shipping_point_zone_label(point),
    "is_pinned": False,
  }


def _seller_shipping_cache_key(
  seller_id: int,
  cargo_type: int,
  *,
  wb_supply_id: str | None = None,
) -> str:
  base = (
    f"wb_sc_points:{SHIPPING_POINTS_CACHE_VERSION}:moscow:"
    f"seller:{seller_id}:cargo:{int(cargo_type)}"
  )
  if wb_supply_id:
    return f"{base}:supply:{wb_supply_id}"
  return base


def shipping_prefetch_lock_key(seller_id: int, wb_supply_id: str | None = None) -> str:
  suffix = wb_supply_id or "general"
  return f"wb_shipping_prefetch_lock:seller:{seller_id}:{suffix}"


def _supply_cargo_cache_key(seller_id: int, wb_supply_id: str) -> str:
  return f"wb_supply_cargo:{SHIPPING_POINTS_CACHE_VERSION}:seller:{seller_id}:supply:{wb_supply_id}"


def cache_supply_cargo_type(seller_id: int, wb_supply_id: str, cargo_type: int) -> None:
  if not wb_supply_id or not cargo_type:
    return
  cache.set(
    _supply_cargo_cache_key(seller_id, wb_supply_id),
    int(cargo_type),
    SUPPLY_CARGO_CACHE_TTL,
  )


def resolve_shipping_cargo_type(
  client,
  *,
  cargo_type: int | None,
  wb_supply_id: str | None,
  seller_id: int | None = None,
) -> int:
  resolved_cargo = cargo_type
  if resolved_cargo is None and wb_supply_id and seller_id:
    cached_cargo = cache.get(_supply_cargo_cache_key(seller_id, wb_supply_id))
    if cached_cargo is not None:
      resolved_cargo = int(cached_cargo)
  if resolved_cargo is None and wb_supply_id:
    try:
      details = client.fetch_supply(wb_supply_id)
      resolved_cargo = int(details.get("cargoType") or 1)
      if seller_id:
        cache_supply_cargo_type(seller_id, wb_supply_id, resolved_cargo)
    except WBApiError:
      resolved_cargo = 1
  if not resolved_cargo or resolved_cargo == 0:
    resolved_cargo = 1
  return int(resolved_cargo)


def read_cached_sc_shipping_points(
  seller_id: int,
  *,
  cargo_type: int,
  wb_supply_id: str | None = None,
) -> list[dict] | None:
  """Список СЦ из Redis — сначала по поставке, затем общий кэш селлера."""
  cargo_candidates = [int(cargo_type)]
  for fallback in SC_LIST_CARGO_TYPES:
    if fallback not in cargo_candidates:
      cargo_candidates.append(fallback)
  key_variants: list[str | None] = []
  if wb_supply_id:
    key_variants.append(wb_supply_id)
  key_variants.append(None)
  for cargo in cargo_candidates:
    for supply_suffix in key_variants:
      cache_key = _seller_shipping_cache_key(
        seller_id,
        cargo,
        wb_supply_id=supply_suffix,
      )
      cached = cache.get(cache_key)
      if isinstance(cached, dict):
        sc_cached = cached.get("sc")
        if isinstance(sc_cached, list) and sc_cached:
          return sc_cached
  return None


def fetch_moscow_region_sc_shipping_points(
  seller: Seller,
  *,
  cargo_type: int | None = None,
  wb_supply_id: str | None = None,
  force_refresh: bool = False,
  cache_only: bool = False,
) -> tuple[list[dict], list[dict], int]:
  """СЦ и склады WB: Москва и МО ~50 км. Только то, что вернул API селлера."""
  from apps.orders.services.assembly import _get_client

  if not seller.fulfillment_id:
    raise ValueError("no_fulfillment")

  client = _get_client(seller)
  resolved_cargo = resolve_shipping_cargo_type(
    client,
    cargo_type=cargo_type,
    wb_supply_id=wb_supply_id,
    seller_id=seller.id,
  )
  if not force_refresh:
    sc_cached = read_cached_sc_shipping_points(
      seller.id,
      cargo_type=resolved_cargo,
      wb_supply_id=wb_supply_id,
    )
    if sc_cached:
      return sc_cached, [], resolved_cargo

  if cache_only:
    return [], [], resolved_cargo

  cache_key = _seller_shipping_cache_key(
    seller.id,
    resolved_cargo,
    wb_supply_id=wb_supply_id,
  )

  merged: dict[int, dict] = {}
  for fetch_city in MOSCOW_REGION_50KM_CITIES:
    for point in _fetch_city_shipping_points(client, fetch_city, SC_LIST_CARGO_TYPES):
      if not _point_supports_any_cargo(point, SC_LIST_CARGO_TYPES):
        continue
      point_id = int(point["id"])
      if point_id in merged:
        merged[point_id] = _union_shipping_point(merged[point_id], point)
      else:
        merged[point_id] = point
    time.sleep(0.06)

  sc_points = _sort_sc_points(_filter_sc_sw_points(list(merged.values())))
  if sc_points:
    cache.set(
      cache_key,
      {
        "sc": sc_points,
        "pp": [],
        "cached_at": timezone.now().isoformat(),
        "seller_id": seller.id,
      },
      ALL_SC_SHIPPING_CACHE_TTL,
    )
    if wb_supply_id:
      cache_supply_cargo_type(seller.id, wb_supply_id, resolved_cargo)
  return sc_points, [], resolved_cargo


def fetch_seller_shipping_points(
  seller: Seller,
  *,
  city: str,
  cargo_type: int | None = None,
  wb_supply_id: str | None = None,
) -> tuple[list[dict], list[dict], int]:
  """Пункты отгрузки для модалки «В доставку»."""
  city = (city or "").strip()
  if not city or city.lower().startswith("москва"):
    return fetch_moscow_region_sc_shipping_points(
      seller,
      cargo_type=cargo_type,
      wb_supply_id=wb_supply_id,
    )

  from apps.orders.services.assembly import _get_client

  client = _get_client(seller)
  resolved_cargo = resolve_shipping_cargo_type(
    client,
    cargo_type=cargo_type,
    wb_supply_id=wb_supply_id,
  )
  points = _fetch_city_shipping_points(client, city, SC_LIST_CARGO_TYPES)
  sc_points = _sort_sc_points(_filter_sc_sw_points(points))
  return sc_points, [], resolved_cargo


def fetch_all_russia_sc_shipping_points(
  seller: Seller,
  *,
  cargo_type: int | None = None,
  wb_supply_id: str | None = None,
  force_refresh: bool = False,
) -> tuple[list[dict], list[dict], int]:
  return fetch_moscow_region_sc_shipping_points(
    seller,
    cargo_type=cargo_type,
    wb_supply_id=wb_supply_id,
    force_refresh=force_refresh,
  )
