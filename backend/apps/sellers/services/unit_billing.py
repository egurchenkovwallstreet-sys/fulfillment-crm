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
  SHIPMENTS_WEEKS_HISTORY,
  _ShippedOrderMeta,
  _barcode_price_map,
  _order_eligible_for_billing,
  _resolve_unit_price,
  _seller_fallback_tariff,
)
from apps.sellers.services.warehouse_filter import (
  get_billing_warehouse_match_ids,
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
def record_shipment_unit_charge_for_order(
  order: Order,
  *,
  seller: Seller,
  charge_date=None,
) -> ShipmentUnitCharge | None:
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

  if charge_date is None:
    charge_date = (order.in_delivery_at or timezone.now()).date()
  elif hasattr(charge_date, "date"):
    charge_date = timezone.localtime(charge_date).date()
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
  if not _order_eligible_for_billing(
    seller,
    meta,
    match_ids=match_ids,
    wb_order_id=wb_order_id,
  ):
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

  from apps.sellers.services.crm_product_stats import WB_STICKER_STOCK_COMMENT
  from apps.sellers.services.sticker_billing import (
    _local_order_index,
    _parse_sticker_key,
    _parse_wb_order_id,
  )
  from apps.warehouse.models import StockOperation

  today = today_local()
  _, current_week_end = calendar_week_bounds_offset(0, today)
  oldest_week_start, _ = calendar_week_bounds_offset(SHIPMENTS_WEEKS_HISTORY - 1, today)
  from_date = oldest_week_start if mode == TARIFF_APPLY_RECALCULATE_ALL else today

  price_by_barcode = _barcode_price_map(seller, marketplace=WB)
  fallback_tariff = _seller_fallback_tariff(seller, marketplace=WB)
  order_index = _local_order_index(seller)
  match_ids = (
    get_billing_warehouse_match_ids(seller)
    if seller_has_warehouse_config(seller)
    else None
  )

  ops = StockOperation.objects.filter(
    product__seller=seller,
    product__marketplace=WB,
    operation_type=StockOperation.OperationType.SHIPMENT,
    comment__icontains=WB_STICKER_STOCK_COMMENT,
    created_at__date__gte=from_date,
    created_at__date__lte=current_week_end,
  ).select_related("product").order_by("created_at")

  updated = 0
  seen_sticker_keys: set[str] = set()
  seen_orders: set[int] = set()

  for op in ops:
    comment = op.comment or ""
    sticker_key = _parse_sticker_key(comment)
    if sticker_key:
      if sticker_key in seen_sticker_keys:
        continue
      seen_sticker_keys.add(sticker_key)

    wb_order_id = _parse_wb_order_id(comment)
    if wb_order_id is None or wb_order_id in seen_orders:
      continue
    seen_orders.add(wb_order_id)

    meta = order_index.get(wb_order_id)
    if meta is None and op.product:
      meta = _ShippedOrderMeta(barcode=(op.product.barcode or "").strip())

    charge_date = timezone.localtime(op.created_at).date()
    if _upsert_wb_unit_charge(
      seller=seller,
      wb_order_id=wb_order_id,
      charge_date=charge_date,
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
