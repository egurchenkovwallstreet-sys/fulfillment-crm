"""Поштучная отправка заказов на сборку и в доставку через WB FBS API."""
from __future__ import annotations

import logging
import os
import time
from collections import defaultdict
from datetime import date

from django.core.cache import cache
from django.db import transaction
from django.db.models import Exists, OuterRef, QuerySet
from django.utils import timezone

from apps.integrations.models import AuditLog
from apps.integrations.wb_client import WBApiError
from apps.orders.models import Order, PickList, Supply
from apps.orders.services.assembly import AssemblyError, _get_client, fetch_stickers_for_orders
from apps.orders.services.assembly_queue import order_in_assembly
from apps.orders.services.wb_status import (
  WB_STAGE_QUERIES,
  WB_STATUS_AFTER_DELIVER,
  WB_SUPPLIER_ASSEMBLY,
  WB_SUPPLIER_DELIVERY,
  WB_SUPPLIER_NEW,
  wb_in_delivery_q,
)
from apps.sellers.models import Seller
from apps.sellers.services.warehouse_filter import (
  filter_orders_for_assembly,
  get_enabled_wb_warehouse_ids,
  seller_has_warehouse_config,
)
from apps.orders.services.marking_verification import (
  VERIFY_ERROR,
  VERIFY_PENDING,
  order_marking_ready,
  verify_marking_orders,
)
from apps.warehouse.services.marking_lookup import resolve_product_requires_marking
from apps.warehouse.services.stock_deduction import (
  StockDeductionError,
  assert_order_stock_deducted_at_print,
  order_sticker_printed_in_crm,
  stock_deduction_info,
)

logger = logging.getLogger(__name__)


class SupplyFlowError(Exception):
  def __init__(self, message: str, *, code: str = "error"):
    super().__init__(message)
    self.code = code


def _get_order(seller: Seller, order_id: int) -> Order:
  order = (
    filter_orders_for_assembly(
      Order.objects.filter(pk=order_id, seller=seller)
      .select_related("product", "pick_list"),
      seller,
    ).first()
  )
  if not order:
    raise SupplyFlowError("Заказ не найден", code="order_not_found")
  return order


def order_can_send_to_assembly(order: Order) -> bool:
  """WB new — можно отправить на сборку (CRM-статус не блокирует, кроме финальных)."""
  if order.status in (
    Order.Status.CANCELLED,
    Order.Status.SHIPPED,
    Order.Status.IN_DELIVERY,
  ):
    return False
  supplier = (order.wb_supplier_status or "").strip()
  return supplier in ("", WB_SUPPLIER_NEW)


def order_can_send_to_delivery(order: Order) -> bool:
  if (order.wb_supplier_status or "").strip() != WB_SUPPLIER_ASSEMBLY:
    return False
  if not order_sticker_printed_in_crm(order):
    return False
  if order.status not in (Order.Status.LABEL_PRINTED, Order.Status.MARKED):
    return False
  if resolve_product_requires_marking(order.product, order.barcode, order.seller):
    return order_marking_ready(order)
  return True


def _parse_deliver_error(exc: WBApiError) -> str:
  text = str(exc).lower()
  if exc.status_code == 409:
    if "shipping" in text or "supplyshipping" in text:
      return (
        "WB требует указать пункт отгрузки (СЦ/ПВЗ) и дату перед передачей в доставку. "
        "Выберите их в окне подтверждения и повторите."
      )
    if "sgtin" in text or "marking" in text or "meta" in text:
      return (
        "WB отклонил передачу в доставку: ошибка маркировки ЧЗ в поставке. "
        "Замените товар, привяжите новый ЧЗ и повторите."
      )
    return f"WB отклонил передачу в доставку: {exc}"
  return str(exc)


def _resolve_supply_cargo_type(client, supply: Supply) -> int:
  if not supply.wb_supply_id:
    return 1
  try:
    details = client.fetch_supply(supply.wb_supply_id)
    cargo = int(details.get("cargoType") or 1)
    return cargo if cargo in (1, 2, 3) else 1
  except WBApiError:
    return 1


def fetch_seller_shipping_points(
  seller: Seller,
  *,
  city: str,
  cargo_type: int | None = None,
  wb_supply_id: str | None = None,
) -> tuple[list[dict], int]:
  """Пункты отгрузки WB для модалки «В доставку»."""
  city = (city or "").strip()
  if not city:
    raise SupplyFlowError("Укажите город для поиска пунктов отгрузки", code="invalid_city")

  client = _get_client(seller)
  resolved_cargo = _resolve_shipping_cargo_type(
    client,
    cargo_type=cargo_type,
    wb_supply_id=wb_supply_id,
  )

  try:
    points = client.fetch_shipping_points(city, resolved_cargo)
  except WBApiError as exc:
    raise SupplyFlowError(
      f"Не удалось загрузить пункты отгрузки WB: {exc}",
      code="wb_shipping_points_failed",
    ) from exc
  points = _merge_pinned_shipping_points(client, resolved_cargo, points)
  points = _filter_delivery_office_points(points)
  return points, resolved_cargo


PINNED_SHIPPING_EXTRA_CITIES: tuple[str, ...] = (
  "Липкинское",
  "Вёшки",
  "Вешки",
  "г.о. Мытищи",
)

VESHKI_SEARCH_CITIES: tuple[str, ...] = (
  "Москва",
  "Мытищи",
  "Вёшки",
  "Вешки",
  "Липкинское",
  "Московская область",
  "Московский",
  "Химки",
  "Королёv",
)

# Города, посёлки и сёла Москвы и МО (~100 км). WB API — только city.
MOSCOW_REGION_100KM_CITIES: tuple[str, ...] = (
  "Москва",
  "Московская область",
  "Мытищи",
  "Вешки",
  "Пушкино",
  "Подольск",
  "Балашиха",
  "Химки",
  "Люберцы",
  "Королёв",
  "Щёлково",
  "Долгопрудный",
  "Одинцово",
  "Красногорск",
  "Домодедово",
  "Видное",
  "Раменское",
  "Жуковский",
  "Ногинск",
  "Электросталь",
  "Коломна",
  "Зеленоград",
  "Истра",
  "Чехов",
  "Ступино",
  "Сергиев Посад",
  "Дмитров",
  "Лобня",
  "Реутов",
  "Фрязино",
  "Орехово-Зуево",
  "Серпухов",
  "Клин",
  "Наро-Фоминск",
  "Егорьевск",
  "Дубна",
  "Павловский Посад",
  "Солнечногorsk",
  "Чашниково",
  "Обухово",
  "Софьино",
  "Коледино",
  "Белые Столбы",
  "Московский",
  "Вёшки",
  "Липкинское",
  "Апрелевка",
  "Бronницы",
  "Верея",
  "Вolokolamsk",
  "Вoskresensk",
  "Гoliцыno",
  "Дedovsk",
  "Зvenigorod",
  "Иvanтеevka",
  "Кotельники",
  "Прotvino",
  "Тaldom",
  "Chernogolovka",
  "Эlektrogorsk",
  "Monino",
  "Nakhabino",
  "Tomilino",
  "Kommunarka",
  "Troitsk",
  "Shcherbinka",
  "Zhavoronki",
  "Razvilka",
  "Sosensky",
  "Klimovsk",
  "Skolkovo",
  "Protvino",
  "Pushchino",
  "Roshal",
  "Ruza",
  "Hotkovo",
  "Yasnogorsk",
  "Elektrougli",
  "Shatura",
  "Bykovo",
  "Kraskovo",
  "Mikhnevo",
  "Marushkino",
  "Andreevka",
  "Saburovo",
  "Yubileyny",
  "Vatutinki",
  "Krekshino",
  "Rumyantsevo",
  "Ashukino",
  "Malakhovka",
  "Peresvet",
  "Iksha",
  "Elektroizolyator",
)


def _dedupe_shipping_cities(*groups: tuple[str, ...]) -> tuple[str, ...]:
  seen: set[str] = set()
  ordered: list[str] = []
  for group in groups:
    for city in group:
      key = city.strip().lower()
      if not key or key in seen:
        continue
      seen.add(key)
      ordered.append(city.strip())
  return tuple(ordered)


def _all_sc_fetch_cities() -> tuple[str, ...]:
  return _dedupe_shipping_cities(MOSCOW_REGION_100KM_CITIES, PINNED_SHIPPING_EXTRA_CITIES)

ALL_SC_SHIPPING_CACHE_TTL = 3600


def _resolve_shipping_cargo_type(
  client,
  *,
  cargo_type: int | None,
  wb_supply_id: str | None,
) -> int:
  resolved_cargo = cargo_type
  if resolved_cargo is None and wb_supply_id:
    try:
      details = client.fetch_supply(wb_supply_id)
      resolved_cargo = int(details.get("cargoType") or 1)
    except WBApiError:
      resolved_cargo = 1
  if not resolved_cargo or resolved_cargo == 0:
    resolved_cargo = 1
  return resolved_cargo


def _is_sc_office_type(point: dict) -> bool:
  return _normalize_text(point.get("officeType")) in ("sc", "sw")


def _is_delivery_office_type(point: dict) -> bool:
  """СЦ и склады WB для FBS-отгрузки (без ПВЗ)."""
  return _is_sc_office_type(point)


def _filter_delivery_office_points(points: list[dict]) -> list[dict]:
  return [
    point for point in points
    if isinstance(point, dict) and _is_delivery_office_type(point)
  ]


def _veshki_env_fallback_point() -> dict | None:
  """ID из .env, если WB API не вернул Вёшки в поиске."""
  raw = (os.environ.get("WB_VESHKI_SHIPPING_POINT_ID") or "").strip()
  if not raw.isdigit():
    return None
  return {
    "id": int(raw),
    "name": "Москва (Вёшки)",
    "address": "Московская область, пос. Вёшки, Липкинское ш., 2-й км, вл1с1",
    "city": "Мытищи",
    "officeType": "sw",
    "cargoTypes": [1, 2, 3],
  }


def _resolve_veshki_shipping_point(client, cargo_type: int) -> dict | None:
  cargo_types = list(PINNED_SHIPPING_CARGO_TYPES)
  if cargo_type not in cargo_types:
    cargo_types.append(cargo_type)
  for fetch_city in VESHKI_SEARCH_CITIES:
    for fetch_cargo in cargo_types:
      try:
        batch = client.fetch_shipping_points(fetch_city, fetch_cargo)
      except WBApiError:
        continue
      for point in batch:
        if not isinstance(point, dict) or point.get("id") is None:
          continue
        if _matches_veshki_lipkinskoe(point):
          return _normalize_pinned_point(point)
  return _veshki_env_fallback_point()


def fetch_moscow_region_sc_shipping_points(
  seller: Seller,
  *,
  cargo_type: int | None = None,
  wb_supply_id: str | None = None,
) -> tuple[list[dict], int]:
  """СЦ и склады WB: только Москва и Московская область (кеш 1 ч)."""
  client = _get_client(seller)
  resolved_cargo = _resolve_shipping_cargo_type(
    client,
    cargo_type=cargo_type,
    wb_supply_id=wb_supply_id,
  )
  cache_key = f"wb_sc_points:v5:moscow:{seller.id}:{resolved_cargo}"
  cached = cache.get(cache_key)
  if isinstance(cached, list) and cached:
    return cached, resolved_cargo

  merged: dict[int, dict] = {}
  fetch_cities = _all_sc_fetch_cities()
  # Сначала города с закреплёнными точками (Вёшки, Пушкино)
  priority = _dedupe_shipping_cities(VESHKI_SEARCH_CITIES, ("Пушкино",))
  rest = tuple(city for city in fetch_cities if city not in priority)
  ordered_cities = _dedupe_shipping_cities(priority, rest)

  for fetch_city in ordered_cities:
    try:
      batch = client.fetch_shipping_points(fetch_city, resolved_cargo)
    except WBApiError:
      continue
    for point in batch:
      if not isinstance(point, dict) or point.get("id") is None:
        continue
      if not _is_delivery_office_type(point):
        continue
      if not _point_supports_cargo(point, resolved_cargo):
        continue
      merged[int(point["id"])] = point
    time.sleep(0.08)

  points = _merge_pinned_shipping_points(client, resolved_cargo, list(merged.values()))
  points = _filter_delivery_office_points(points)
  points.sort(key=lambda point: (
    0 if _matches_veshki_lipkinskoe(point) else 1,
    _normalize_text(point.get("city")),
    _normalize_text(point.get("name")),
  ))
  if points:
    cache.set(cache_key, points, ALL_SC_SHIPPING_CACHE_TTL)
  return points, resolved_cargo


def fetch_all_russia_sc_shipping_points(
  seller: Seller,
  *,
  cargo_type: int | None = None,
  wb_supply_id: str | None = None,
) -> tuple[list[dict], int]:
  """Обратная совместимость scope=all_sc → только Москва и МО."""
  return fetch_moscow_region_sc_shipping_points(
    seller,
    cargo_type=cargo_type,
    wb_supply_id=wb_supply_id,
  )


def _normalize_text(value: object) -> str:
  return str(value or "").strip().lower().replace("ё", "е")


def _point_supports_cargo(point: dict, cargo_type: int) -> bool:
  cargo_types = point.get("cargoTypes") or []
  if not cargo_types:
    return True
  return int(cargo_type) in {int(item) for item in cargo_types}


def _point_haystack(point: dict) -> str:
  return " ".join(
    _normalize_text(point.get(key))
    for key in ("name", "address", "city")
  )


def _is_pinned_sc_point(point: dict) -> bool:
  return _matches_veshki_lipkinskoe(point) or _matches_pushkino_sc(point)


def _is_visible_sc_point(point: dict) -> bool:
  if _is_pinned_sc_point(point):
    return True
  return _is_sc_office_type(point)


def _matches_veshki_lipkinskoe(point: dict) -> bool:
  haystack = _point_haystack(point)
  if "липкин" in haystack:
    return True
  if "2" in haystack and "км" in haystack and ("липкин" in haystack or "веш" in haystack):
    return True
  if "веш" in haystack and ("москва" in haystack or "мытищ" in haystack or "москов" in haystack):
    return True
  return "вешки" in haystack or "veshki" in haystack


def _matches_pushkino_sc(point: dict) -> bool:
  return "пушкино" in _point_haystack(point)


PINNED_SHIPPING_POINT_MATCHERS = (
  ("veshki_lipkinskoe", _matches_veshki_lipkinskoe),
  ("pushkino_sc", _matches_pushkino_sc),
)

PINNED_SHIPPING_POINT_FETCH_CITIES: tuple[str, ...] = VESHKI_SEARCH_CITIES + ("Пушкино",)

PINNED_SHIPPING_CARGO_TYPES: tuple[int, ...] = (1, 2, 3)


def _fetch_pinned_shipping_pool(client, cargo_type: int) -> list[dict]:
  """Пул для закреплённых точек: приоритетные города + все типы груза."""
  pool: list[dict] = []
  cargo_types = list(PINNED_SHIPPING_CARGO_TYPES)
  if cargo_type not in cargo_types:
    cargo_types.append(cargo_type)
  cities = _dedupe_shipping_cities(
    PINNED_SHIPPING_POINT_FETCH_CITIES,
    PINNED_SHIPPING_EXTRA_CITIES,
  )
  for fetch_city in cities:
    for fetch_cargo in cargo_types:
      try:
        pool.extend(client.fetch_shipping_points(fetch_city, fetch_cargo))
      except WBApiError:
        continue
  return pool


def _normalize_pinned_point(point: dict) -> dict:
  """Вёшки в WB часто приходит как склад (sw) — показываем в списке СЦ."""
  normalized = dict(point)
  office_type = _normalize_text(normalized.get("officeType"))
  if office_type not in ("sc", "sw", "pp"):
    normalized["officeType"] = "sw"
  return normalized


def _merge_pinned_shipping_points(
  client,
  cargo_type: int,
  points: list[dict],
) -> list[dict]:
  """Всегда добавить в список СЦ Вешки (Липкинское) и СЦ Пушкино."""
  merged = list(points or [])
  known_ids = {
    int(point["id"])
    for point in merged
    if isinstance(point, dict) and point.get("id") is not None
  }
  found_keys: set[str] = set()
  for point in merged:
    if not isinstance(point, dict):
      continue
    for key, matcher in PINNED_SHIPPING_POINT_MATCHERS:
      if key not in found_keys and matcher(point):
        found_keys.add(key)

  if len(found_keys) == len(PINNED_SHIPPING_POINT_MATCHERS):
    pool = []
  else:
    pool = _fetch_pinned_shipping_pool(client, cargo_type)

  if pool:
    for key, matcher in PINNED_SHIPPING_POINT_MATCHERS:
      if key in found_keys:
        continue
      for point in pool:
        if not isinstance(point, dict) or point.get("id") is None:
          continue
        if not matcher(point):
          continue
        point_id = int(point["id"])
        if point_id in known_ids:
          found_keys.add(key)
          break
        merged.append(_normalize_pinned_point(point))
        known_ids.add(point_id)
        found_keys.add(key)
        break

  if not any(_matches_veshki_lipkinskoe(point) for point in merged if isinstance(point, dict)):
    veshki = _resolve_veshki_shipping_point(client, cargo_type)
    if veshki:
      point_id = int(veshki["id"])
      if point_id not in known_ids:
        merged.insert(0, veshki)
        known_ids.add(point_id)

  return merged


def _apply_shipping_method(
  client,
  supply: Supply,
  *,
  shipping_point_id: int,
  shipping_date: date,
  shipping_type: str = "selfShipping",
) -> None:
  if supply.status == Supply.Status.CONFIRMED:
    return
  if not supply.wb_supply_id:
    raise SupplyFlowError("У поставки нет ID WB", code="no_supply")
  try:
    client.set_supplies_shipping_method([{
      "supplyId": supply.wb_supply_id,
      "shippingPointId": shipping_point_id,
      "shippingDt": shipping_date.isoformat(),
      "shippingType": shipping_type,
    }])
  except WBApiError as exc:
    raise SupplyFlowError(
      f"Не удалось установить параметры отгрузки WB: {exc}",
      code="wb_shipping_method_failed",
    ) from exc


def _ensure_marking_verified_for_delivery(seller: Seller, order: Order, *, user=None) -> None:
  """Перед доставкой — свежий опрос WB по ЧЗ, если в CRM ещё не подтверждено."""
  if not resolve_product_requires_marking(order.product, order.barcode, order.seller):
    return
  if order_marking_ready(order):
    return
  if not (order.marking_code or "").strip():
    raise SupplyFlowError(
      "Сначала отсканируйте и привяжите Честный знак (DataMatrix).",
      code="marking_required",
    )
  try:
    verify_marking_orders(seller, [order.id], user=user)
  except AssemblyError as exc:
    raise SupplyFlowError(str(exc), code="marking_verify_failed") from exc
  order.refresh_from_db()
  verify_status = (order.marking_verify_status or "").strip()
  if verify_status == VERIFY_ERROR:
    raise SupplyFlowError(
      order.marking_verify_error
      or "ЧЗ отклонён WB — замените товар и отсканируйте другой экземпляр.",
      code="marking_error",
    )
  if verify_status == VERIFY_PENDING:
    raise SupplyFlowError(
      "WB ещё проверяет Честный знак (обычно несколько минут). "
      "Дождитесь подтверждения или нажмите «Обновить из WB».",
      code="marking_pending",
    )
  if not order_marking_ready(order):
    raise SupplyFlowError(
      "Честный знак не подтверждён WB — нельзя передать в доставку.",
      code="marking_not_ready",
    )


def _get_or_create_forming_supply(
  seller: Seller,
  wb_warehouse_id: int,
  client,
) -> Supply:
  """Одна формирующаяся поставка WB на склад."""
  supply = (
    Supply.objects.filter(
      seller=seller,
      wb_warehouse_id=wb_warehouse_id,
      status=Supply.Status.FORMING,
    )
    .exclude(wb_supply_id="")
    .order_by("-created_at")
    .first()
  )
  if supply:
    return supply

  supply_name = f"CRM-S{seller.id}-W{wb_warehouse_id}-{timezone.now():%Y%m%d%H%M}"
  wb_supply_id = client.create_supply(supply_name)
  return Supply.objects.create(
    seller=seller,
    wb_supply_id=wb_supply_id,
    wb_warehouse_id=wb_warehouse_id,
    status=Supply.Status.FORMING,
  )


def _create_new_forming_supply(
  seller: Seller,
  wb_warehouse_id: int,
  client,
) -> Supply:
  """Новая пустая поставка WB на склад (перенос неотсканированных заказов)."""
  supply_name = f"CRM-S{seller.id}-W{wb_warehouse_id}-{timezone.now():%Y%m%d%H%M%S}"
  wb_supply_id = client.create_supply(supply_name)
  return Supply.objects.create(
    seller=seller,
    wb_supply_id=wb_supply_id,
    wb_warehouse_id=wb_warehouse_id,
    status=Supply.Status.FORMING,
  )


def order_can_move_to_new_supply(order: Order) -> bool:
  if order.wb_warehouse_id is None:
    return False
  if (order.wb_supplier_status or "").strip() != WB_SUPPLIER_ASSEMBLY:
    return False
  return order_in_assembly(order)


@transaction.atomic
def move_orders_to_new_supply(
  seller: Seller,
  order_ids: list[int],
  *,
  user=None,
) -> dict:
  if not order_ids:
    raise SupplyFlowError("Не выбраны заказы для переноса", code="empty")

  orders = list(
    Order.objects.filter(seller=seller, pk__in=order_ids).select_related("product", "seller")
  )
  if len(orders) != len(set(order_ids)):
    raise SupplyFlowError("Некоторые заказы не найдены", code="not_found")

  movable: list[Order] = []
  skipped: list[dict] = []
  for order in orders:
    if order_can_move_to_new_supply(order):
      movable.append(order)
    else:
      skipped.append({
        "order_id": order.id,
        "wb_order_id": order.wb_order_id,
        "error": "Заказ уже отсканирован или не на сборке",
      })

  if not movable:
    raise SupplyFlowError(
      "Нет заказов для переноса — можно переносить только неотсканированные на сборке",
      code="nothing_to_move",
    )

  by_warehouse: dict[int, list[Order]] = defaultdict(list)
  for order in movable:
    by_warehouse[int(order.wb_warehouse_id)].append(order)

  client = _get_client(seller)
  created_supplies: list[dict] = []

  for wb_warehouse_id, wh_orders in by_warehouse.items():
    new_supply = _create_new_forming_supply(seller, wb_warehouse_id, client)
    wb_order_ids = [int(order.wb_order_id) for order in wh_orders]
    try:
      client.add_orders_to_supply(new_supply.wb_supply_id, wb_order_ids)
    except WBApiError as exc:
      new_supply.delete()
      raise SupplyFlowError(
        f"WB не принял перенос заказов в новую поставку: {exc}",
        code="wb_move_failed",
      ) from exc

    old_supply_ids: set[int] = set()
    for order in wh_orders:
      for old_supply in order.supplies.filter(
        status__in=(Supply.Status.FORMING, Supply.Status.READY),
      ):
        old_supply.orders.remove(order)
        old_supply_ids.add(old_supply.id)
      new_supply.orders.add(order)

    for old_supply_id in old_supply_ids:
      old_supply = Supply.objects.filter(pk=old_supply_id).first()
      if old_supply:
        refresh_supply_readiness(old_supply)

    created_supplies.append({
      "supply_id": new_supply.id,
      "wb_supply_id": new_supply.wb_supply_id,
      "wb_warehouse_id": wb_warehouse_id,
      "orders_moved": len(wh_orders),
    })

  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.SUPPLY,
    message=f"Перенос {len(movable)} заказов в {len(created_supplies)} новых поставок",
    details={
      "order_ids": [order.id for order in movable],
      "supplies": created_supplies,
      "skipped": skipped,
    },
  )

  return {
    "moved_count": len(movable),
    "supplies": created_supplies,
    "skipped": skipped,
  }


def _append_orders_to_forming_supply(
  seller: Seller,
  supply: Supply,
  orders: list[Order],
  *,
  client,
  user=None,
) -> tuple[int, str, int]:
  """Добавить заказы в поставку WB. Возвращает (стикеры, ошибка, добавлено)."""
  existing_wb_ids = set(supply.orders.values_list("wb_order_id", flat=True))
  new_orders = [order for order in orders if order.wb_order_id not in existing_wb_ids]
  if not new_orders:
    return 0, "", 0

  client.add_orders_to_supply(
    supply.wb_supply_id,
    [order.wb_order_id for order in new_orders],
  )
  supply.orders.add(*new_orders)

  stickers_fetched = 0
  sticker_error = ""
  try:
    stickers_fetched = fetch_stickers_for_orders(seller, new_orders, user=user)
  except AssemblyError as exc:
    sticker_error = str(exc)

  for order in new_orders:
    order.status = Order.Status.IN_PICKING
    order.wb_supplier_status = WB_SUPPLIER_ASSEMBLY
    order.save(update_fields=["status", "wb_supplier_status", "updated_at"])

  return stickers_fetched, sticker_error, len(new_orders)


@transaction.atomic
def send_order_to_assembly(seller: Seller, order_id: int, *, user=None) -> dict:
  """
  Один заказ → поставка WB склада → статус confirm («На сборке»).
  Все заказы одного склада попадают в одну поставку.
  """
  order = _get_order(seller, order_id)

  if not order_can_send_to_assembly(order):
    raise SupplyFlowError(
      f"Заказ WB #{order.wb_order_id} нельзя отправить на сборку "
      f"(статус CRM: {order.get_status_display()}, WB: {order.wb_supplier_status or 'new'}).",
      code="invalid_status",
    )

  if order.wb_warehouse_id is None:
    raise SupplyFlowError(
      f"У заказа WB #{order.wb_order_id} не указан склад WB.",
      code="no_warehouse",
    )

  client = _get_client(seller)
  try:
    supply = _get_or_create_forming_supply(seller, order.wb_warehouse_id, client)
    stickers_fetched, sticker_error, added = _append_orders_to_forming_supply(
      seller,
      supply,
      [order],
      client=client,
      user=user,
    )
    if added == 0:
      order.refresh_from_db()
      return {
        "order": order,
        "wb_supply_id": supply.wb_supply_id,
        "stickers_fetched": 0,
        "sticker_error": "",
      }
  except WBApiError as exc:
    AuditLog.objects.create(
      user=user,
      seller=seller,
      action_type=AuditLog.ActionType.API_ERROR,
      message=f"Ошибка отправки на сборку WB #{order.wb_order_id}: {exc}",
      details={"order_id": order.id, "status_code": exc.status_code},
    )
    raise SupplyFlowError(str(exc), code="wb_assembly_failed") from exc

  order.refresh_from_db()

  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.ASSEMBLY,
    message=f"На сборку (WB): заказ #{order.wb_order_id}, поставка {supply.wb_supply_id}",
    details={
      "order_id": order.id,
      "wb_supply_id": supply.wb_supply_id,
      "wb_warehouse_id": order.wb_warehouse_id,
      "stickers_fetched": stickers_fetched,
      "sticker_error": sticker_error,
    },
  )

  return {
    "order": order,
    "wb_supply_id": supply.wb_supply_id,
    "stickers_fetched": stickers_fetched,
    "sticker_error": sticker_error,
  }


def _fetch_supply_barcode_payload(client, wb_supply_id: str) -> tuple[str, str, str]:
  """ШК поставки WB доступен только после deliver; иногда API отвечает с задержкой."""
  supply_barcode_file = ""
  supply_barcode_value = ""
  last_error = ""
  for attempt in range(4):
    if attempt > 0:
      time.sleep(0.5 * attempt)
    try:
      barcode_payload = client.fetch_supply_barcode(wb_supply_id)
      if isinstance(barcode_payload, dict):
        supply_barcode_file = barcode_payload.get("file") or ""
        supply_barcode_value = str(barcode_payload.get("barcode") or "")
      if supply_barcode_file:
        return supply_barcode_file, supply_barcode_value, ""
    except WBApiError as exc:
      last_error = str(exc)
  return supply_barcode_file, supply_barcode_value, last_error


def _complete_order_in_delivery(
  order: Order,
  supply: Supply,
  *,
  seller: Seller,
  user=None,
) -> dict:
  """Перевести один заказ в «В доставке». Остаток списан при печати стикера."""
  order.status = Order.Status.IN_DELIVERY
  order.wb_supplier_status = WB_SUPPLIER_DELIVERY
  order.wb_status = WB_STATUS_AFTER_DELIVER
  if order.in_delivery_at is None:
    order.in_delivery_at = timezone.now()
  order.save(
    update_fields=[
      "status",
      "wb_supplier_status",
      "wb_status",
      "in_delivery_at",
      "updated_at",
    ],
  )
  stock_info = stock_deduction_info(order)
  try:
    from apps.sellers.services.liter_billing import record_shipment_liter_charge_for_order

    record_shipment_liter_charge_for_order(order, seller=seller)
  except Exception:
    logger.exception("liter shipment charge failed for order %s", order.id)
  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.SUPPLY,
    message=f"В доставку (WB): заказ #{order.wb_order_id}, поставка {supply.wb_supply_id}",
    details={
      "order_id": order.id,
      "wb_supply_id": supply.wb_supply_id,
    },
  )
  return stock_info


def _detach_order_from_pick_list(order: Order) -> None:
  from apps.orders.services.assembly import _detach_order_from_pick_list as detach

  if not order.pick_list_id:
    return
  detach(order)
  order.save(update_fields=["pick_list", "updated_at"])


def _cleanup_pick_lists_after_supply_delivery(supply: Supply, *, seller: Seller) -> None:
  """Удалить пустые листы подбора склада после передачи поставки в доставку."""
  qs = PickList.objects.filter(
    seller=seller,
    is_completed=False,
    marketplace="wb",
  )
  if supply.wb_warehouse_id is not None:
    qs = qs.filter(wb_warehouse_id=supply.wb_warehouse_id)
  for pick_list in qs:
    if not pick_list.items.exists():
      pick_list.delete()


def _assert_all_supply_orders_ready_for_deliver(supply: Supply) -> None:
  orders = _supply_orders(supply)
  if not orders:
    raise SupplyFlowError("В поставке нет заказов", code="not_ready")
  not_ready = [order for order in orders if not order_can_send_to_delivery(order)]
  if not_ready:
    sample = not_ready[0]
    reason = order_delivery_block_reason(sample) or "не готов"
    raise SupplyFlowError(
      f"В поставке WB {supply.wb_supply_id} {len(not_ready)} из {len(orders)} "
      f"заказ(ов) ещё не готовы ({reason}). "
      "Дособерите все заказы или перенесите неготовые в новую поставку.",
      code="not_ready",
    )


def _prepare_supply_orders_for_deliver(
  seller: Seller,
  supply: Supply,
  *,
  user=None,
) -> None:
  for order in _supply_orders(supply):
    if not order_can_send_to_delivery(order):
      continue
    _ensure_marking_verified_for_delivery(seller, order, user=user)
    try:
      assert_order_stock_deducted_at_print(order)
    except StockDeductionError as exc:
      raise SupplyFlowError(str(exc), code="insufficient_stock") from exc
  _assert_all_supply_orders_ready_for_deliver(supply)


def _finalize_supply_after_wb_deliver(
  supply: Supply,
  *,
  seller: Seller,
  user=None,
  primary_order: Order | None = None,
) -> tuple[Order, dict]:
  """
  WB переводит в доставку всю поставку целиком — синхронизируем все заказы CRM
  и сразу убираем лист подбора.
  """
  last_order = primary_order
  last_stock: dict = {}
  for order in _supply_orders(supply):
    if order.status == Order.Status.IN_DELIVERY:
      _detach_order_from_pick_list(order)
      continue
    _detach_order_from_pick_list(order)
    last_stock = _complete_order_in_delivery(
      order,
      supply,
      seller=seller,
      user=user,
    )
    last_order = order
  _cleanup_pick_lists_after_supply_delivery(supply, seller=seller)
  if last_order is None:
    raise SupplyFlowError("В поставке нет заказов для CRM", code="not_ready")
  return last_order, last_stock


def _delivery_result(
  order: Order,
  supply: Supply,
  stock_info: dict,
  supply_barcode_file: str,
  supply_barcode_value: str,
  supply_barcode_error: str,
  *,
  seller: Seller,
  user=None,
) -> dict:
  if supply_barcode_error and not supply_barcode_file:
    AuditLog.objects.create(
      user=user,
      seller=seller,
      action_type=AuditLog.ActionType.API_ERROR,
      message=f"WB не вернул ШК поставки {supply.wb_supply_id}: {supply_barcode_error}",
      details={
        "order_id": order.id,
        "supply_id": supply.id,
        "wb_supply_id": supply.wb_supply_id,
      },
    )
  result = {
    "order": order,
    "supply_id": supply.id,
    "wb_supply_id": supply.wb_supply_id,
    "supply_barcode_file": supply_barcode_file,
    "supply_barcode": supply_barcode_value,
    "stock": stock_info,
  }
  if supply_barcode_error and not supply_barcode_file:
    result["supply_barcode_error"] = supply_barcode_error
  return result


@transaction.atomic
def send_order_to_delivery(
  seller: Seller,
  order_id: int,
  *,
  user=None,
  shipping_point_id: int | None = None,
  shipping_date: date | None = None,
  shipping_type: str = "selfShipping",
) -> dict:
  """
  Один заказ → deliver поставки WB → complete+waiting («В доставке»).
  WB переводит в доставку всю поставку — в CRM обновляются все её заказы.
  """
  order = _get_order(seller, order_id)

  if not order_can_send_to_delivery(order):
    requires_marking = resolve_product_requires_marking(
      order.product, order.barcode, order.seller,
    )
    hint = ""
    if requires_marking and not order.marking_bound:
      hint = " Сначала привяжите Честный знак и распечатайте стикер."
    elif requires_marking and (order.marking_verify_status or "").strip() == VERIFY_PENDING:
      hint = " WB ещё проверяет Честный знак — подождите несколько минут."
    elif requires_marking and (order.marking_verify_status or "").strip() == VERIFY_ERROR:
      hint = f" {order.marking_verify_error or 'ЧЗ отклонён — замените товар.'}"
    elif order.status not in (Order.Status.LABEL_PRINTED, Order.Status.MARKED):
      hint = " Сначала отсканируйте баркод и распечатайте стикер FBS."
    raise SupplyFlowError(
      f"Заказ WB #{order.wb_order_id} не готов к отправке в доставку.{hint}",
      code="not_ready",
    )

  supply_qs = Supply.objects.filter(
    seller=seller,
    orders=order,
    status__in=(
      Supply.Status.FORMING,
      Supply.Status.READY,
      Supply.Status.CONFIRMED,
    ),
  ).exclude(wb_supply_id="")
  if order.wb_warehouse_id is not None:
    supply_qs = supply_qs.filter(wb_warehouse_id=order.wb_warehouse_id)
  supply = supply_qs.order_by("-created_at").first()
  if not supply:
    raise SupplyFlowError(
      f"Не найдена поставка WB для заказа #{order.wb_order_id} "
      f"на складе {order.wb_warehouse_id or '—'}. "
      "Отправьте заказ на сборку заново.",
      code="no_supply",
    )
  if (
    order.wb_warehouse_id is not None
    and supply.wb_warehouse_id is not None
    and supply.wb_warehouse_id != order.wb_warehouse_id
  ):
    raise SupplyFlowError(
      f"Поставка WB не соответствует складу заказа #{order.wb_order_id}.",
      code="warehouse_mismatch",
    )

  client = _get_client(seller)

  if order.status == Order.Status.IN_DELIVERY:
    raise SupplyFlowError(
      f"Заказ WB #{order.wb_order_id} уже передан в доставку.",
      code="already_delivered",
    )

  supply_barcode_file = ""
  supply_barcode_value = ""
  supply_barcode_error = ""

  if supply.status == Supply.Status.CONFIRMED:
    supply_barcode_file, supply_barcode_value, supply_barcode_error = _fetch_supply_barcode_payload(
      client,
      supply.wb_supply_id,
    )
    order, stock_info = _finalize_supply_after_wb_deliver(
      supply,
      seller=seller,
      user=user,
      primary_order=order,
    )
    return _delivery_result(
      order,
      supply,
      stock_info,
      supply_barcode_file,
      supply_barcode_value,
      supply_barcode_error,
      user=user,
      seller=seller,
    )

  _prepare_supply_orders_for_deliver(seller, supply, user=user)

  try:
    if not shipping_point_id or not shipping_date:
      raise SupplyFlowError(
        "Укажите пункт отгрузки (СЦ/ПВЗ) и дату отгрузки — это обязательно для WB.",
        code="shipping_required",
      )
    _apply_shipping_method(
      client,
      supply,
      shipping_point_id=shipping_point_id,
      shipping_date=shipping_date,
      shipping_type=shipping_type,
    )
    client.deliver_supply(supply.wb_supply_id)
  except WBApiError as exc:
    AuditLog.objects.create(
      user=user,
      seller=seller,
      action_type=AuditLog.ActionType.API_ERROR,
      message=f"Ошибка доставки WB #{order.wb_order_id}: {exc}",
      details={
        "order_id": order.id,
        "wb_supply_id": supply.wb_supply_id,
        "status_code": exc.status_code,
      },
    )
    raise SupplyFlowError(_parse_deliver_error(exc), code="wb_deliver_failed") from exc

  supply_barcode_file, supply_barcode_value, supply_barcode_error = _fetch_supply_barcode_payload(
    client,
    supply.wb_supply_id,
  )

  order, stock_info = _finalize_supply_after_wb_deliver(
    supply,
    seller=seller,
    user=user,
    primary_order=order,
  )

  supply.status = Supply.Status.CONFIRMED
  supply.supply_barcode_printed = bool(supply_barcode_file)
  supply.save(update_fields=["status", "supply_barcode_printed", "updated_at"])

  return _delivery_result(
    order,
    supply,
    stock_info,
    supply_barcode_file,
    supply_barcode_value,
    supply_barcode_error,
    user=user,
    seller=seller,
  )


def delivery_stage_orders_queryset(seller: Seller) -> QuerySet:
  """Вкладка «В доставке»: в поставке WB, ШК поставки ещё не отсканирован на складе."""
  confirmed_unscanned_supply = Supply.objects.filter(
    seller=seller,
    status=Supply.Status.CONFIRMED,
    wb_scanned_at__isnull=True,
    orders__id=OuterRef("pk"),
  )
  return filter_orders_for_assembly(
    Order.objects.filter(seller=seller, assembly_hidden=False)
    .filter(wb_in_delivery_q())
    .annotate(_awaiting_supply_scan=Exists(confirmed_unscanned_supply))
    .filter(_awaiting_supply_scan=True),
    seller,
  )


def count_delivery_stage_orders(seller: Seller) -> int:
  return delivery_stage_orders_queryset(seller).count()


def delivery_stage_supplies_queryset(seller: Seller) -> QuerySet:
  """Поставки на вкладке «В доставке»: переданы в WB, ШК ещё не отсканирован на складе."""
  qs = Supply.objects.filter(
    seller=seller,
    status=Supply.Status.CONFIRMED,
    wb_scanned_at__isnull=True,
  ).exclude(wb_supply_id="")
  if seller_has_warehouse_config(seller):
    enabled = get_enabled_wb_warehouse_ids(seller)
    if not enabled:
      return qs.none()
    qs = qs.filter(wb_warehouse_id__in=enabled)
  return qs


def new_stage_orders_queryset(seller: Seller) -> QuerySet:
  """Заказы вкладки «Новые» на странице сборки — как в ЛК WB + готовые к отправке."""
  qs = filter_orders_for_assembly(
    Order.objects.filter(seller=seller, assembly_hidden=False),
    seller,
  )
  qs = qs.filter(WB_STAGE_QUERIES["new"]())
  if seller.wb_new_order_ids:
    qs = qs.filter(wb_order_id__in=seller.wb_new_order_ids)
  return qs.exclude(
    status__in=[
      Order.Status.CANCELLED,
      Order.Status.SHIPPED,
      Order.Status.IN_DELIVERY,
    ],
  )


def count_new_orders_for_barcode(seller: Seller, barcode: str) -> int:
  """Заказы вкладки «Новые» по баркоду на обслуживаемых FBS-складах."""
  barcode = (barcode or "").strip()
  if not barcode:
    return 0
  return new_stage_orders_queryset(seller).filter(barcode=barcode).count()


def count_new_orders_for_barcode_on_warehouse(
  seller: Seller,
  barcode: str,
  wb_warehouse_id: int | None,
) -> int:
  """Заказы «Новые» по баркоду на конкретном FBS-складе WB."""
  barcode = (barcode or "").strip()
  if not barcode or not wb_warehouse_id:
    return 0
  return new_stage_orders_queryset(seller).filter(
    barcode=barcode,
    wb_warehouse_id=wb_warehouse_id,
  ).count()


def picking_stage_orders_queryset(seller: Seller) -> QuerySet:
  """Заказы вкладки «На сборке» (confirm) на странице сборки."""
  qs = filter_orders_for_assembly(
    Order.objects.filter(seller=seller, assembly_hidden=False).filter(
      WB_STAGE_QUERIES["confirm"](),
    ),
    seller,
  )
  return qs.exclude(
    status__in=[
      Order.Status.CANCELLED,
      Order.Status.SHIPPED,
    ],
  )


def count_picking_orders_for_barcode_on_warehouse(
  seller: Seller,
  barcode: str,
  wb_warehouse_id: int | None,
) -> int:
  """Заказы «На сборке» по баркоду на конкретном FBS-складе WB."""
  barcode = (barcode or "").strip()
  if not barcode or not wb_warehouse_id:
    return 0
  return picking_stage_orders_queryset(seller).filter(
    barcode=barcode,
    wb_warehouse_id=wb_warehouse_id,
  ).count()


def order_counts_by_barcode_on_warehouse(qs: QuerySet, wb_warehouse_id: int | None) -> dict[str, int]:
  """Счётчик заказов по баркоду на складе WB (одним запросом)."""
  from django.db.models import Count

  if not wb_warehouse_id:
    return {}
  rows = (
    qs.filter(wb_warehouse_id=wb_warehouse_id)
    .exclude(barcode="")
    .values("barcode")
    .annotate(n=Count("id"))
  )
  return {str(row["barcode"]): int(row["n"]) for row in rows if row.get("barcode")}


def count_orders_ready_for_assembly(seller: Seller) -> int:
  return new_stage_orders_queryset(seller).count()


def get_assembly_stage_counts(seller: Seller) -> dict[str, int]:
  """Счётчики вкладок сборки FBS (без скрытых заказов)."""
  confirm_qs = picking_stage_orders_queryset(seller)
  in_delivery = filter_orders_for_assembly(
    Order.objects.filter(seller=seller, assembly_hidden=False).filter(wb_in_delivery_q()),
    seller,
  ).count()
  return {
    "new": new_stage_orders_queryset(seller).count(),
    "in_picking": confirm_qs.count(),
    "in_delivery": in_delivery,
  }


def send_orders_to_assembly_bulk(
  seller: Seller,
  *,
  order_ids: list[int] | None = None,
  user=None,
) -> dict:
  """Отправить на сборку заказы: одна поставка WB на каждый склад."""
  qs = new_stage_orders_queryset(seller).select_related("product")
  if order_ids is not None:
    qs = qs.filter(pk__in=order_ids)

  orders = [order for order in qs if order_can_send_to_assembly(order)]
  if not orders:
    raise SupplyFlowError(
      "Нет заказов для отправки на сборку. Обновите заказы из WB.",
      code="no_orders",
    )

  by_warehouse: dict[int, list[Order]] = defaultdict(list)
  errors: list[dict] = []
  for order in orders:
    if order.wb_warehouse_id is None:
      errors.append({
        "order_id": order.id,
        "wb_order_id": order.wb_order_id,
        "error": "Не указан склад WB",
      })
      continue
    by_warehouse[order.wb_warehouse_id].append(order)

  client = _get_client(seller)
  sent = 0
  stickers_total = 0

  for wb_warehouse_id, wh_orders in by_warehouse.items():
    try:
      supply = _get_or_create_forming_supply(seller, wb_warehouse_id, client)
      stickers_fetched, sticker_error, added = _append_orders_to_forming_supply(
        seller,
        supply,
        wh_orders,
        client=client,
        user=user,
      )
      sent += added
      stickers_total += stickers_fetched
      if sticker_error:
        errors.append({
          "wb_warehouse_id": wb_warehouse_id,
          "wb_supply_id": supply.wb_supply_id,
          "error": sticker_error,
        })
    except (SupplyFlowError, WBApiError) as exc:
      for order in wh_orders:
        errors.append({
          "order_id": order.id,
          "wb_order_id": order.wb_order_id,
          "error": str(exc),
        })

  if sent == 0 and errors:
    raise SupplyFlowError(
      f"Не удалось отправить ни одного заказа. Пример: {errors[0]['error']}",
      code="batch_failed",
    )

  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.ASSEMBLY,
    message=(
      f"Массовая отправка на сборку: {sent} заказов, "
      f"поставок WB: {len(by_warehouse)}"
    ),
    details={
      "sent": sent,
      "total": len(orders),
      "supplies": len(by_warehouse),
      "errors": errors,
    },
  )

  return {
    "sent": sent,
    "total": len(orders),
    "supplies": len(by_warehouse),
    "stickers_fetched": stickers_total,
    "errors": errors,
  }


def order_delivery_block_reason(order: Order) -> str | None:
  if order_can_send_to_delivery(order):
    return None
  if (order.wb_supplier_status or "").strip() != WB_SUPPLIER_ASSEMBLY:
    return "Не на сборке WB"
  if not order_sticker_printed_in_crm(order):
    return "Нет стикера FBS — отсканируйте в сборке"
  if order.status not in (Order.Status.LABEL_PRINTED, Order.Status.MARKED):
    return "Нет стикера FBS — отсканируйте в сборке"
  if resolve_product_requires_marking(order.product, order.barcode, order.seller):
    verify_status = (order.marking_verify_status or "").strip()
    if verify_status == "pending":
      return "WB проверяет ЧЗ (несколько минут) — в доставку после подтверждения WB"
    if verify_status == "error":
      return order.marking_verify_error or "ЧЗ отклонён WB — замените товар"
    if not order_marking_ready(order):
      return "Нужен Честный знак"
  return "Не готов к доставке"


def _supply_orders(supply: Supply) -> list[Order]:
  return list(
    supply.orders.select_related("product", "seller").all(),
  )


def refresh_supply_readiness(supply: Supply) -> Supply:
  if supply.status not in (Supply.Status.FORMING, Supply.Status.READY):
    return supply
  orders = _supply_orders(supply)
  if not orders:
    return supply
  all_ready = all(order_can_send_to_delivery(order) for order in orders)
  new_status = Supply.Status.READY if all_ready else Supply.Status.FORMING
  if supply.status != new_status:
    supply.status = new_status
    supply.save(update_fields=["status", "updated_at"])
  return supply


def supply_can_deliver(supply: Supply) -> bool:
  if supply.status not in (Supply.Status.FORMING, Supply.Status.READY):
    return False
  if not supply.wb_supply_id:
    return False
  orders = _supply_orders(supply)
  return bool(orders) and all(order_can_send_to_delivery(order) for order in orders)


@transaction.atomic
def send_supply_to_delivery(
  seller: Seller,
  supply_id: int,
  *,
  user=None,
  shipping_point_id: int | None = None,
  shipping_date: date | None = None,
  shipping_type: str = "selfShipping",
) -> dict:
  supply = (
    Supply.objects.filter(pk=supply_id, seller=seller)
    .prefetch_related("orders__product", "orders__seller")
    .first()
  )
  if not supply:
    raise SupplyFlowError("Поставка не найдена", code="not_found")

  refresh_supply_readiness(supply)
  if not supply_can_deliver(supply):
    reasons = [
      reason
      for order in _supply_orders(supply)
      if (reason := order_delivery_block_reason(order))
    ]
    raise SupplyFlowError(
      "Поставка не готова: " + (reasons[0] if reasons else "проверьте заказы"),
      code="not_ready",
    )

  client = _get_client(seller)
  supply_barcode_file = ""
  supply_barcode_value = ""
  supply_barcode_error = ""

  if supply.status in (Supply.Status.FORMING, Supply.Status.READY):
    _prepare_supply_orders_for_deliver(seller, supply, user=user)
    try:
      if not shipping_point_id or not shipping_date:
        raise SupplyFlowError(
          "Укажите пункт отгрузки (СЦ/ПВЗ) и дату отгрузки — это обязательно для WB.",
          code="shipping_required",
        )
      _apply_shipping_method(
        client,
        supply,
        shipping_point_id=shipping_point_id,
        shipping_date=shipping_date,
        shipping_type=shipping_type,
      )
      client.deliver_supply(supply.wb_supply_id)
    except WBApiError as exc:
      raise SupplyFlowError(_parse_deliver_error(exc), code="wb_deliver_failed") from exc
    supply_barcode_file, supply_barcode_value, supply_barcode_error = _fetch_supply_barcode_payload(
      client,
      supply.wb_supply_id,
    )
    supply.status = Supply.Status.CONFIRMED
    supply.supply_barcode_printed = bool(supply_barcode_file)
    supply.save(update_fields=["status", "supply_barcode_printed", "updated_at"])
  elif supply.status == Supply.Status.CONFIRMED:
    supply_barcode_file, supply_barcode_value, supply_barcode_error = _fetch_supply_barcode_payload(
      client,
      supply.wb_supply_id,
    )

  primary_order = next(
    (order for order in _supply_orders(supply) if order_can_send_to_delivery(order)),
    None,
  ) or (_supply_orders(supply)[0] if _supply_orders(supply) else None)
  if primary_order is None:
    raise SupplyFlowError(
      "В поставке нет заказов для передачи в доставку.",
      code="not_ready",
    )
  order, stock_info = _finalize_supply_after_wb_deliver(
    supply,
    seller=seller,
    user=user,
    primary_order=primary_order,
  )
  last_result = _delivery_result(
    order,
    supply,
    stock_info,
    supply_barcode_file,
    supply_barcode_value,
    supply_barcode_error,
    user=user,
    seller=seller,
  )

  return last_result


def send_supplies_to_delivery_bulk(
  seller: Seller,
  *,
  supply_ids: list[int] | None = None,
  user=None,
  shipping_point_id: int | None = None,
  shipping_date: date | None = None,
  shipping_type: str = "selfShipping",
) -> dict:
  qs = Supply.objects.filter(
    seller=seller,
    status__in=(Supply.Status.FORMING, Supply.Status.READY),
  ).prefetch_related("orders__product", "orders__seller")
  if supply_ids is not None:
    qs = qs.filter(pk__in=supply_ids)

  delivered = 0
  errors: list[dict] = []
  barcode_files: list[str] = []

  for supply in qs:
    refresh_supply_readiness(supply)
    if not supply_can_deliver(supply):
      continue
    try:
      result = send_supply_to_delivery(
        seller,
        supply.id,
        user=user,
        shipping_point_id=shipping_point_id,
        shipping_date=shipping_date,
        shipping_type=shipping_type,
      )
      delivered += 1
      if result.get("supply_barcode_file"):
        barcode_files.append(result["supply_barcode_file"])
    except SupplyFlowError as exc:
      errors.append({
        "supply_id": supply.id,
        "wb_supply_id": supply.wb_supply_id,
        "error": str(exc),
      })

  if delivered == 0 and errors:
    raise SupplyFlowError(
      f"Не удалось передать ни одной поставки. Пример: {errors[0]['error']}",
      code="batch_failed",
    )

  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.SUPPLY,
    message=f"Массовая передача в доставку: {delivered} поставок",
    details={"delivered": delivered, "errors": errors},
  )

  return {
    "delivered": delivered,
    "errors": errors,
    "supply_barcode_files": barcode_files,
  }


def fetch_supply_barcode(seller: Seller, supply_id: int) -> dict:
  supply = Supply.objects.filter(pk=supply_id, seller=seller).first()
  if not supply:
    raise SupplyFlowError("Поставка не найдена", code="not_found")
  if supply.status != Supply.Status.CONFIRMED:
    raise SupplyFlowError(
      "ШК поставки доступен только после передачи в доставку",
      code="not_confirmed",
    )
  if not supply.wb_supply_id:
    raise SupplyFlowError("У поставки нет ID WB", code="no_wb_id")

  client = _get_client(seller)
  supply_barcode_file, supply_barcode_value, last_error = _fetch_supply_barcode_payload(
    client,
    supply.wb_supply_id,
  )

  if not supply_barcode_file:
    raise SupplyFlowError(
      last_error or "WB не вернул изображение ШК поставки",
      code="empty_barcode",
    )

  supply.supply_barcode_printed = True
  supply.save(update_fields=["supply_barcode_printed", "updated_at"])

  return {
    "wb_supply_id": supply.wb_supply_id,
    "supply_barcode_file": supply_barcode_file,
    "supply_barcode": supply_barcode_value,
  }
