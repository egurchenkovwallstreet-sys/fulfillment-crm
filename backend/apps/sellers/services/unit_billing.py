"""Фиксация начислений отгрузки по тарифу за единицу."""
from __future__ import annotations

import logging
import time
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.integrations.marketplace import OZON, WB, normalize_marketplace
from apps.integrations.wb_client import REQUEST_INTERVAL_SEC, WBApiError
from apps.orders.models import Order, OzonPosting, Supply
from apps.sellers.models import Seller, ShipmentUnitCharge
from apps.sellers.services.calendar_periods import calendar_week_bounds_offset, today_local
from apps.sellers.services.seller_billing_stats import (
  MAX_SUPPLY_ORDER_FETCHES,
  SHIPMENTS_WEEKS_HISTORY,
  WB_ORDERS_LOOKBACK_DAYS,
  _barcode_price_map,
  _build_wb_order_index,
  _fetch_supply_order_ids,
  _get_client,
  _order_eligible_for_billing,
  _resolve_unit_price,
  _seller_fallback_tariff,
  _supply_handoff_at,
)
from apps.sellers.services.warehouse_filter import (
  get_enabled_warehouse_match_ids,
  seller_has_warehouse_config,
)
from apps.sellers.services.wb_order_stats import SellerAnalyticsError
from apps.warehouse.models import Product
from apps.warehouse.services.liter_pricing import seller_uses_liter_pricing

logger = logging.getLogger(__name__)

TARIFF_APPLY_RECALCULATE_ALL = "recalculate_all"
TARIFF_APPLY_FROM_TODAY = "from_today"
TARIFF_APPLY_MODES = {TARIFF_APPLY_RECALCULATE_ALL, TARIFF_APPLY_FROM_TODAY}


class TariffBillingError(Exception):
  pass


def _unit_price_for_barcode(
  seller: Seller,
  barcode: str,
  *,
  marketplace: str,
  price_by_barcode: dict[str, Decimal] | None = None,
  fallback_tariff: Decimal | None = None,
) -> Decimal | None:
  prices = price_by_barcode if price_by_barcode is not None else _barcode_price_map(seller, marketplace=marketplace)
  fallback = fallback_tariff if fallback_tariff is not None else _seller_fallback_tariff(seller, marketplace=marketplace)
  code = (barcode or "").strip()
  if code and code in prices:
    return prices[code]
  return fallback


@transaction.atomic
def record_shipment_unit_charge_for_order(order: Order, *, seller: Seller) -> ShipmentUnitCharge | None:
  if seller_uses_liter_pricing(seller):
    return None
  if not order.wb_order_id:
    return None
  existing = ShipmentUnitCharge.objects.filter(seller=seller, wb_order_id=order.wb_order_id).first()
  if existing:
    return existing

  product = order.product
  barcode = (order.barcode or (product.barcode if product else "") or "").strip()
  unit_price = _unit_price_for_barcode(seller, barcode, marketplace=WB)
  if unit_price is None:
    return None

  charge_date = (order.in_delivery_at or timezone.now()).date()
  return ShipmentUnitCharge.objects.create(
    seller=seller,
    product=product,
    barcode=barcode,
    marketplace=WB,
    order=order,
    wb_order_id=int(order.wb_order_id),
    charge_date=charge_date,
    quantity=1,
    unit_price=unit_price,
    amount=unit_price,
  )


@transaction.atomic
def record_shipment_unit_charge_for_ozon_posting(
  posting: OzonPosting,
  *,
  seller: Seller,
) -> ShipmentUnitCharge | None:
  if seller_uses_liter_pricing(seller):
    return None
  existing = ShipmentUnitCharge.objects.filter(ozon_posting=posting).first()
  if existing:
    return existing

  barcode = (posting.barcode or "").strip()
  unit_price = _unit_price_for_barcode(seller, barcode, marketplace=OZON)
  if unit_price is None:
    return None

  qty = max(1, posting.quantity or 1)
  charge_date = (posting.shipped_at or timezone.now()).date()
  product = Product.objects.filter(seller=seller, marketplace=OZON, barcode=barcode).first()
  return ShipmentUnitCharge.objects.create(
    seller=seller,
    product=product,
    barcode=barcode,
    marketplace=OZON,
    ozon_posting=posting,
    charge_date=charge_date,
    quantity=qty,
    unit_price=unit_price,
    amount=unit_price * qty,
  )


def _upsert_wb_unit_charge(
  *,
  seller: Seller,
  wb_order_id: int,
  charge_date,
  meta,
  price_by_barcode: dict[str, Decimal],
  fallback_tariff: Decimal | None,
  match_ids,
) -> bool:
  if not _order_eligible_for_billing(seller, meta, match_ids=match_ids):
    return False

  unit_price = _resolve_unit_price(
    meta,
    price_by_barcode=price_by_barcode,
    fallback_tariff=fallback_tariff,
  )
  if unit_price is None:
    return False

  order = Order.objects.filter(seller=seller, wb_order_id=wb_order_id).select_related("product").first()
  product = order.product if order else None
  barcode = (meta.barcode if meta else "") or (order.barcode if order else "") or (product.barcode if product else "")

  ShipmentUnitCharge.objects.update_or_create(
    seller=seller,
    wb_order_id=wb_order_id,
    defaults={
      "product": product,
      "barcode": barcode,
      "marketplace": WB,
      "order": order,
      "charge_date": charge_date,
      "quantity": 1,
      "unit_price": unit_price,
      "amount": unit_price,
    },
  )
  return True


def rebuild_wb_unit_shipment_charges(seller: Seller, *, mode: str) -> int:
  if seller_uses_liter_pricing(seller):
    return 0
  if mode not in TARIFF_APPLY_MODES:
    raise TariffBillingError("Неизвестный режим применения тарифа")

  today = today_local()
  _, current_week_end = calendar_week_bounds_offset(0, today)
  oldest_week_start, _ = calendar_week_bounds_offset(SHIPMENTS_WEEKS_HISTORY - 1, today)
  from_date = oldest_week_start if mode == TARIFF_APPLY_RECALCULATE_ALL else today

  price_by_barcode = _barcode_price_map(seller, marketplace=WB)
  fallback_tariff = _seller_fallback_tariff(seller, marketplace=WB)
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

  updated = 0
  api_fetches = 0
  seen_orders: set[int] = set()

  for wb_supply in wb_supplies:
    if not wb_supply.get("done"):
      continue
    handoff_at = _supply_handoff_at(wb_supply)
    if handoff_at is None:
      continue
    handoff_date = timezone.localtime(handoff_at).date()
    if handoff_date > current_week_end:
      continue
    if handoff_date < from_date:
      continue

    wb_supply_id = str(wb_supply.get("id") or "")
    if not wb_supply_id or api_fetches >= MAX_SUPPLY_ORDER_FETCHES:
      continue

    crm_supply = crm_supplies.get(wb_supply_id)
    order_wb_ids = _fetch_supply_order_ids(client, wb_supply, crm_supply=crm_supply)
    api_fetches += 1
    time.sleep(REQUEST_INTERVAL_SEC)

    for wb_order_id in order_wb_ids:
      if wb_order_id in seen_orders:
        continue
      seen_orders.add(wb_order_id)
      meta = order_index.get(wb_order_id)
      if _upsert_wb_unit_charge(
        seller=seller,
        wb_order_id=wb_order_id,
        charge_date=handoff_date,
        meta=meta,
        price_by_barcode=price_by_barcode,
        fallback_tariff=fallback_tariff,
        match_ids=match_ids,
      ):
        updated += 1

  return updated


def rebuild_ozon_unit_shipment_charges(seller: Seller, *, mode: str) -> int:
  if seller_uses_liter_pricing(seller):
    return 0
  if mode not in TARIFF_APPLY_MODES:
    raise TariffBillingError("Неизвестный режим применения тарифа")

  today = today_local()
  _, current_week_end = calendar_week_bounds_offset(0, today)
  oldest_week_start, _ = calendar_week_bounds_offset(SHIPMENTS_WEEKS_HISTORY - 1, today)
  from_date = oldest_week_start if mode == TARIFF_APPLY_RECALCULATE_ALL else today

  price_by_barcode = _barcode_price_map(seller, marketplace=OZON)
  fallback_tariff = _seller_fallback_tariff(seller, marketplace=OZON)
  updated = 0

  qs = OzonPosting.objects.filter(
    seller=seller,
    shipped_at__isnull=False,
    shipped_at__date__gte=from_date,
    shipped_at__date__lte=current_week_end,
  )
  for posting in qs.iterator():
    ship_date = timezone.localtime(posting.shipped_at).date()
    barcode = (posting.barcode or "").strip()
    unit_price = price_by_barcode.get(barcode) or fallback_tariff
    if unit_price is None:
      continue
    qty = max(1, posting.quantity or 1)
    product = Product.objects.filter(seller=seller, marketplace=OZON, barcode=barcode).first()
    ShipmentUnitCharge.objects.update_or_create(
      ozon_posting=posting,
      defaults={
        "seller": seller,
        "product": product,
        "barcode": barcode,
        "marketplace": OZON,
        "charge_date": ship_date,
        "quantity": qty,
        "unit_price": unit_price,
        "amount": unit_price * qty,
      },
    )
    updated += 1

  return updated


def rebuild_unit_shipment_charges(seller: Seller, *, mode: str) -> dict:
  wb_count = rebuild_wb_unit_shipment_charges(seller, mode=mode)
  ozon_count = rebuild_ozon_unit_shipment_charges(seller, mode=mode)
  return {"wb": wb_count, "ozon": ozon_count, "total": wb_count + ozon_count}


def apply_tariff_billing_policy(seller: Seller, mode: str) -> dict:
  if mode not in TARIFF_APPLY_MODES:
    raise TariffBillingError("Укажите режим: recalculate_all или from_today")

  from apps.sellers.services.admin_billing_cache import invalidate_admin_billing_for_fulfillment
  from apps.sellers.services.liter_billing import recalculate_liter_shipment_charges
  from apps.warehouse.services.liter_pricing import seller_uses_liter_pricing

  if seller_uses_liter_pricing(seller):
    result = recalculate_liter_shipment_charges(seller, mode=mode)
  else:
    result = rebuild_unit_shipment_charges(seller, mode=mode)

  invalidate_admin_billing_for_fulfillment(seller.fulfillment_id)
  return {"mode": mode, **result}
