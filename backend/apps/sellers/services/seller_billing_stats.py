"""Отгрузки FBS — по факту передачи поставки на склад WB."""
from __future__ import annotations

import re
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone

from apps.integrations.wb_client import REQUEST_INTERVAL_SEC, WBApiError, WBClient
from apps.integrations.wb_crypto import TokenCryptoError, decrypt_token
from apps.orders.models import Order, Supply
from apps.orders.services.supply_sync import _parse_wb_datetime
from apps.sellers.models import Seller
from apps.sellers.services.calendar_periods import (
  calendar_week_bounds,
  calendar_week_bounds_offset,
  iter_week_days,
  today_local,
)
from apps.sellers.services.wb_order_stats import SellerAnalyticsError
from apps.sellers.services.warehouse_filter import (
  get_enabled_warehouse_match_ids,
  order_matches_enabled_warehouse,
  seller_has_warehouse_config,
)
from apps.warehouse.models import Product

CRM_SUPPLY_NAME_RE = re.compile(r"^CRM-(\d+)-")
MAX_SUPPLY_ORDER_FETCHES = 300
SHIPMENTS_WEEKS_HISTORY = 4
WB_ORDERS_LOOKBACK_DAYS = 30


@dataclass
class _ShippedOrderMeta:
  barcode: str = ""
  warehouse_id: int | None = None
  office_id: int | None = None


def _get_client(seller: Seller) -> WBClient:
  if not seller.wb_api_token_encrypted:
    raise SellerAnalyticsError("Токен WB не настроен для этого селлера")
  try:
    token = decrypt_token(seller.wb_api_token_encrypted)
  except TokenCryptoError as exc:
    raise SellerAnalyticsError("Не удалось расшифровать токен WB") from exc
  return WBClient(token)


def _supply_handoff_at(wb_supply: dict):
  for key in ("scanDt", "scan_dt", "closedAt", "closed_at"):
    parsed = _parse_wb_datetime(wb_supply.get(key))
    if parsed is not None:
      return parsed
  return None


def _order_ids_from_wb_supply_name(name: str) -> list[int]:
  match = CRM_SUPPLY_NAME_RE.match(name or "")
  if not match:
    return []
  return [int(match.group(1))]


def _barcode_price_map(seller: Seller, *, marketplace: str | None = None) -> dict[str, Decimal]:
  prices: dict[str, Decimal] = {}
  qs = Product.objects.filter(seller=seller).select_related("price_group")
  if marketplace:
    qs = qs.filter(marketplace=marketplace)
  for product in qs:
    price = product.processing_price
    if price is not None:
      prices[product.barcode] = price
  return prices


def _seller_fallback_tariff(seller: Seller, *, marketplace: str | None = None) -> Decimal | None:
  """Общий тариф селлера, если у всех товаров одна individual_price."""
  qs = Product.objects.filter(seller=seller, individual_price__isnull=False)
  if marketplace:
    qs = qs.filter(marketplace=marketplace)
  distinct = list(qs.values_list("individual_price", flat=True).distinct())
  if len(distinct) == 1:
    return distinct[0]
  return None


def _build_wb_order_index(seller: Seller, client: WBClient) -> dict[int, _ShippedOrderMeta]:
  """Баркод и склад заказа: CRM + архив WB (не только заказы, прошедшие через CRM)."""
  index: dict[int, _ShippedOrderMeta] = {}

  for wb_order_id, barcode, warehouse_id in Order.objects.filter(seller=seller).values_list(
    "wb_order_id",
    "barcode",
    "wb_warehouse_id",
  ):
    index[int(wb_order_id)] = _ShippedOrderMeta(
      barcode=str(barcode or "").strip(),
      warehouse_id=warehouse_id,
    )

  try:
    wb_orders = client.fetch_fbs_orders_for_period(days=WB_ORDERS_LOOKBACK_DAYS)
  except WBApiError:
    wb_orders = None

  if wb_orders is not None:
    for order in wb_orders.orders:
      meta = index.get(order.wb_order_id)
      if meta is None:
        index[order.wb_order_id] = _ShippedOrderMeta(
          barcode=order.barcode,
          warehouse_id=order.warehouse_id,
          office_id=order.office_id,
        )
        continue
      if not meta.barcode and order.barcode:
        meta.barcode = order.barcode
      if meta.warehouse_id is None and order.warehouse_id is not None:
        meta.warehouse_id = order.warehouse_id
      if meta.office_id is None and order.office_id is not None:
        meta.office_id = order.office_id

  return index


def _fetch_supply_order_ids(
  client: WBClient,
  wb_supply: dict,
  *,
  crm_supply: Supply | None,
) -> list[int]:
  """ID заказов в поставке — в первую очередь из WB API."""
  wb_supply_id = str(wb_supply.get("id") or "")
  if wb_supply_id:
    try:
      order_ids = client.fetch_supply_order_ids(wb_supply_id)
      if order_ids:
        return order_ids
    except WBApiError:
      pass

  if crm_supply is not None:
    crm_ids = list(crm_supply.orders.values_list("wb_order_id", flat=True))
    if crm_ids:
      return crm_ids

  return _order_ids_from_wb_supply_name(str(wb_supply.get("name") or ""))


def _order_eligible_for_billing(
  seller: Seller,
  meta: _ShippedOrderMeta | None,
  *,
  match_ids: set[int] | None,
) -> bool:
  """Только заказы с включённых FBS-складов фулфилмента."""
  if not seller_has_warehouse_config(seller):
    return True
  if meta is None:
    return False
  return order_matches_enabled_warehouse(
    seller,
    meta.warehouse_id,
    meta.office_id,
    match_ids=match_ids,
  )


def _resolve_unit_price(
  meta: _ShippedOrderMeta | None,
  *,
  price_by_barcode: dict[str, Decimal],
  fallback_tariff: Decimal | None,
) -> Decimal | None:
  if meta and meta.barcode:
    price = price_by_barcode.get(meta.barcode)
    if price is not None:
      return price
  return fallback_tariff


def _sum_shipped_orders(
  seller: Seller,
  wb_order_ids: list[int],
  *,
  order_index: dict[int, _ShippedOrderMeta],
  price_by_barcode: dict[str, Decimal],
  fallback_tariff: Decimal | None,
  match_ids: set[int] | None,
) -> tuple[int, Decimal]:
  if not wb_order_ids:
    return 0, Decimal("0")

  count = 0
  amount = Decimal("0")
  seen: set[int] = set()
  for wb_order_id in wb_order_ids:
    if wb_order_id in seen:
      continue
    seen.add(wb_order_id)

    meta = order_index.get(wb_order_id)
    if not _order_eligible_for_billing(seller, meta, match_ids=match_ids):
      continue

    count += 1
    unit_price = _resolve_unit_price(
      meta,
      price_by_barcode=price_by_barcode,
      fallback_tariff=fallback_tariff,
    )
    if unit_price is not None:
      amount += unit_price

  return count, amount


def _week_start_for(day: date) -> date:
  return day - timedelta(days=day.weekday())


def _build_week_payload(
  week_start: date,
  week_end: date,
  *,
  daily_counts: dict[date, int],
  daily_amounts: dict[date, Decimal],
  supplies_per_week: dict[date, int],
  today: date,
) -> dict:
  days = [
    {
      "date": day.isoformat(),
      "weekday": label,
      "orders": daily_counts.get(day, 0),
      "amount": daily_amounts.get(day, Decimal("0")),
    }
    for day, label in iter_week_days(week_start)
  ]
  return {
    "week_start": week_start.isoformat(),
    "week_end": week_end.isoformat(),
    "total": sum(day["orders"] for day in days),
    "total_amount": sum((day["amount"] for day in days), Decimal("0")),
    "supplies_count": supplies_per_week.get(week_start, 0),
    "is_current": week_start <= today <= week_end,
    "days": days,
  }


def load_weekly_shipped_orders(seller: Seller, *, weeks: int = SHIPMENTS_WEEKS_HISTORY) -> dict:
  """
  Заказы, переданные на склад WB по календарным неделям (пн–вс, МСК).
  Источник: GET /api/v3/supplies (done) + order-ids из WB API.
  Учитываются заказы только с включённых FBS-складов фулфилмента.
  """
  today = today_local()
  current_week_start, current_week_end = calendar_week_bounds(today)
  oldest_week_start, _ = calendar_week_bounds_offset(weeks - 1, today)

  daily_counts: dict[date, int] = defaultdict(int)
  daily_amounts: dict[date, Decimal] = defaultdict(lambda: Decimal("0"))
  supplies_per_week: dict[date, int] = defaultdict(int)

  price_by_barcode = _barcode_price_map(seller)
  fallback_tariff = _seller_fallback_tariff(seller)

  client = _get_client(seller)
  try:
    wb_supplies = client.fetch_supplies()
  except WBApiError as exc:
    raise SellerAnalyticsError(str(exc)) from exc

  order_index = _build_wb_order_index(seller, client)
  match_ids = (
    get_enabled_warehouse_match_ids(seller)
    if seller_has_warehouse_config(seller)
    else None
  )

  crm_supplies = {
    supply.wb_supply_id: supply
    for supply in Supply.objects.filter(seller=seller).exclude(wb_supply_id="").prefetch_related("orders")
  }

  api_fetches = 0

  for wb_supply in wb_supplies:
    if not wb_supply.get("done"):
      continue

    handoff_at = _supply_handoff_at(wb_supply)
    if handoff_at is None:
      continue

    handoff_date = timezone.localtime(handoff_at).date()
    if not (oldest_week_start <= handoff_date <= current_week_end):
      continue

    wb_supply_id = str(wb_supply.get("id") or "")
    if not wb_supply_id:
      continue

    if api_fetches >= MAX_SUPPLY_ORDER_FETCHES:
      break

    crm_supply = crm_supplies.get(wb_supply_id)
    order_wb_ids = _fetch_supply_order_ids(client, wb_supply, crm_supply=crm_supply)
    api_fetches += 1
    time.sleep(REQUEST_INTERVAL_SEC)

    order_count, order_amount = _sum_shipped_orders(
      seller,
      order_wb_ids,
      order_index=order_index,
      price_by_barcode=price_by_barcode,
      fallback_tariff=fallback_tariff,
      match_ids=match_ids,
    )
    if order_count <= 0:
      continue

    daily_counts[handoff_date] += order_count
    daily_amounts[handoff_date] += order_amount
    supplies_per_week[_week_start_for(handoff_date)] += 1

  weeks_data = [
    _build_week_payload(
      *calendar_week_bounds_offset(weeks_ago, today),
      daily_counts=daily_counts,
      daily_amounts=daily_amounts,
      supplies_per_week=supplies_per_week,
      today=today,
    )
    for weeks_ago in range(weeks)
  ]

  return {
    "today": today.isoformat(),
    "weeks": weeks_data,
  }


def _decimal_amount(value) -> Decimal:
  if isinstance(value, Decimal):
    return value
  return Decimal(str(value or "0"))


def merge_weekly_shipments_payloads(
  payloads: list[dict],
  *,
  weeks: int = SHIPMENTS_WEEKS_HISTORY,
) -> dict:
  """Суммирует отгрузки нескольких селлеров по календарным неделям."""
  today = today_local()
  merged_weeks: list[dict] = []
  for weeks_ago in range(weeks):
    week_start, week_end = calendar_week_bounds_offset(weeks_ago, today)
    merged_weeks.append({
      "week_start": week_start.isoformat(),
      "week_end": week_end.isoformat(),
      "total": 0,
      "total_amount": Decimal("0"),
      "supplies_count": 0,
      "is_current": weeks_ago == 0,
      "days": [
        {
          "date": day.isoformat(),
          "weekday": label,
          "orders": 0,
          "amount": Decimal("0"),
        }
        for day, label in iter_week_days(week_start)
      ],
    })

  for payload in payloads:
    if not payload or not payload.get("weeks"):
      continue
    for week_index, week in enumerate(payload["weeks"]):
      if week_index >= len(merged_weeks):
        break
      target_week = merged_weeks[week_index]
      target_week["total"] += week.get("total", 0)
      target_week["total_amount"] += _decimal_amount(week.get("total_amount"))
      target_week["supplies_count"] += week.get("supplies_count", 0)
      target_week["is_current"] = target_week["is_current"] or week.get("is_current", False)
      for day_index, day in enumerate(week.get("days") or []):
        if day_index >= len(target_week["days"]):
          break
        target_day = target_week["days"][day_index]
        target_day["orders"] += day.get("orders", 0)
        target_day["amount"] += _decimal_amount(day.get("amount"))

  return {
    "today": today.isoformat(),
    "weeks": merged_weeks,
  }


def load_admin_billing_dashboard(*, fulfillment=None, marketplace: str = "wb") -> dict:
  """Отгрузки и суммы по тарифу: по каждому селлеру и общий итог."""
  from apps.integrations.marketplace import OZON, WB, normalize_marketplace
  from apps.sellers.services.liter_billing import (
    load_weekly_liter_shipment_charges,
    load_weekly_storage_charges,
  )
  from apps.sellers.services.ozon_billing_stats import load_weekly_ozon_shipped_orders
  from apps.warehouse.services.liter_pricing import seller_uses_liter_pricing

  mp = normalize_marketplace(marketplace)
  is_ozon = mp == OZON

  sellers = Seller.objects.filter(is_active=True)
  if fulfillment:
    sellers = sellers.filter(fulfillment=fulfillment)
  if is_ozon:
    sellers = sellers.filter(ozon_enabled=True)
  else:
    sellers = sellers.filter(wb_enabled=True)
  sellers = sellers.order_by("company_name")
  seller_rows: list[dict] = []
  successful_payloads: list[dict] = []

  def _liter_billing_fields(seller: Seller) -> dict:
    fields = {"pricing_mode": seller.pricing_mode}
    if seller_uses_liter_pricing(seller):
      fields["liter_storage_chart"] = load_weekly_storage_charges(seller, marketplace=mp)
      fields["liter_shipments_chart"] = load_weekly_liter_shipment_charges(seller, marketplace=mp)
    return fields

  for seller in sellers:
    if is_ozon:
      if not (seller.ozon_client_id and seller.ozon_api_key_encrypted):
        seller_rows.append({
          "seller_id": seller.id,
          "company_name": seller.company_name,
          "weekly_shipments": None,
          "error": "Ключи Ozon не настроены",
          **_liter_billing_fields(seller),
        })
        continue
      try:
        shipments = load_weekly_ozon_shipped_orders(seller)
        successful_payloads.append(shipments)
        seller_rows.append({
          "seller_id": seller.id,
          "company_name": seller.company_name,
          "weekly_shipments": shipments,
          "error": None,
          **_liter_billing_fields(seller),
        })
      except SellerAnalyticsError as exc:
        seller_rows.append({
          "seller_id": seller.id,
          "company_name": seller.company_name,
          "weekly_shipments": None,
          "error": str(exc),
          **_liter_billing_fields(seller),
        })
      continue

    if not seller.wb_api_token_encrypted:
      seller_rows.append({
        "seller_id": seller.id,
        "company_name": seller.company_name,
        "weekly_shipments": None,
        "error": "Токен WB не настроен",
        **_liter_billing_fields(seller),
      })
      continue
    try:
      shipments = load_weekly_shipped_orders(seller)
      successful_payloads.append(shipments)
      seller_rows.append({
        "seller_id": seller.id,
        "company_name": seller.company_name,
        "weekly_shipments": shipments,
        "error": None,
        **_liter_billing_fields(seller),
      })
    except SellerAnalyticsError as exc:
      seller_rows.append({
        "seller_id": seller.id,
        "company_name": seller.company_name,
        "weekly_shipments": None,
        "error": str(exc),
        **_liter_billing_fields(seller),
      })

  combined = merge_weekly_shipments_payloads(successful_payloads)
  return {
    "today": combined["today"],
    "marketplace": mp,
    "combined": combined,
    "sellers": seller_rows,
  }
