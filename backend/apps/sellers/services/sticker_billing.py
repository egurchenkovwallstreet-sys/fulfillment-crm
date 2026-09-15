"""Биллинг отгрузок WB — по факту печати FBS-стикера в CRM (единоразово на заказ)."""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.utils import timezone

from apps.integrations.marketplace import WB
from apps.orders.models import Order
from apps.sellers.models import Seller, ShipmentUnitCharge
from apps.sellers.services.calendar_periods import (
  calendar_week_bounds,
  calendar_week_bounds_offset,
  today_local,
)
from apps.sellers.services.crm_product_stats import WB_STICKER_STOCK_COMMENT
from apps.sellers.services.seller_billing_stats import (
  SHIPMENTS_WEEKS_HISTORY,
  _ShippedOrderMeta,
  _barcode_price_map,
  _build_week_payload,
  _order_eligible_for_billing,
  _resolve_unit_price,
  _seller_fallback_tariff,
  _week_start_for,
)
from apps.sellers.services.warehouse_filter import (
  get_billing_warehouse_match_ids,
  seller_has_warehouse_config,
)
from apps.warehouse.models import StockOperation

STICKER_KEY_IN_COMMENT_RE = re.compile(r"стикер FBS ([^,]+),")
WB_ORDER_IN_COMMENT_RE = re.compile(r"заказ #(\d+)")


@dataclass(frozen=True)
class _StickerPrintEvent:
  wb_order_id: int | None
  event_date: date
  amount: Decimal | None
  meta: _ShippedOrderMeta | None


def _parse_sticker_key(comment: str) -> str:
  match = STICKER_KEY_IN_COMMENT_RE.search(comment or "")
  return (match.group(1) or "").strip()


def _parse_wb_order_id(comment: str) -> int | None:
  match = WB_ORDER_IN_COMMENT_RE.search(comment or "")
  if not match:
    return None
  try:
    return int(match.group(1))
  except (TypeError, ValueError):
    return None


def _local_order_index(seller: Seller) -> dict[int, _ShippedOrderMeta]:
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
  return index


def _meta_for_order(order: Order) -> _ShippedOrderMeta:
  return _ShippedOrderMeta(
    barcode=str(order.barcode or "").strip(),
    warehouse_id=order.wb_warehouse_id,
  )


def _order_sticker_event_date(order: Order) -> date | None:
  event_dt = order.sticker_fetched_at or order.in_delivery_at
  if event_dt is None:
    return None
  return timezone.localtime(event_dt).date()


def _iter_sticker_print_events(
  seller: Seller,
  *,
  oldest_week_start: date,
  current_week_end: date,
) -> list[_StickerPrintEvent]:
  """
  Единоразовый учёт печати стикера в CRM на заказ.
  Источники (по приоритету): ShipmentUnitCharge → Order.has_sticker → StockOperation.
  """
  events: list[_StickerPrintEvent] = []
  seen_wb_order_ids: set[int] = set()
  seen_sticker_keys: set[str] = set()

  order_index = _local_order_index(seller)

  charges = (
    ShipmentUnitCharge.objects.filter(
      seller=seller,
      marketplace=WB,
      wb_order_id__isnull=False,
      charge_date__gte=oldest_week_start,
      charge_date__lte=current_week_end,
    )
    .order_by("charge_date", "id")
  )
  for charge in charges:
    wb_order_id = int(charge.wb_order_id)
    if wb_order_id in seen_wb_order_ids:
      continue
    seen_wb_order_ids.add(wb_order_id)
    meta = order_index.get(wb_order_id) or _ShippedOrderMeta(barcode=str(charge.barcode or "").strip())
    events.append(
      _StickerPrintEvent(
        wb_order_id=wb_order_id,
        event_date=charge.charge_date,
        amount=charge.amount,
        meta=meta,
      )
    )

  sticker_orders = Order.objects.filter(
    seller=seller,
    has_sticker=True,
    wb_order_id__isnull=False,
  ).exclude(wb_order_id__in=seen_wb_order_ids)
  for order in sticker_orders:
    event_date = _order_sticker_event_date(order)
    if event_date is None or not (oldest_week_start <= event_date <= current_week_end):
      continue
    wb_order_id = int(order.wb_order_id)
    seen_wb_order_ids.add(wb_order_id)
    events.append(
      _StickerPrintEvent(
        wb_order_id=wb_order_id,
        event_date=event_date,
        amount=None,
        meta=order_index.get(wb_order_id) or _meta_for_order(order),
      )
    )

  ops = (
    StockOperation.objects.filter(
      product__seller=seller,
      product__marketplace=WB,
      operation_type=StockOperation.OperationType.SHIPMENT,
      comment__icontains=WB_STICKER_STOCK_COMMENT,
      created_at__date__gte=oldest_week_start,
      created_at__date__lte=current_week_end,
    )
    .select_related("product")
    .order_by("created_at")
  )
  for op in ops:
    comment = op.comment or ""
    sticker_key = _parse_sticker_key(comment)
    if sticker_key:
      if sticker_key in seen_sticker_keys:
        continue
      seen_sticker_keys.add(sticker_key)

    wb_order_id = _parse_wb_order_id(comment)
    if wb_order_id is not None:
      if wb_order_id in seen_wb_order_ids:
        continue
      seen_wb_order_ids.add(wb_order_id)

    meta = order_index.get(wb_order_id) if wb_order_id is not None else None
    if meta is None and op.product:
      meta = _ShippedOrderMeta(barcode=(op.product.barcode or "").strip())

    events.append(
      _StickerPrintEvent(
        wb_order_id=wb_order_id,
        event_date=timezone.localtime(op.created_at).date(),
        amount=None,
        meta=meta,
      )
    )

  return events


def record_billing_on_sticker_print(order: Order, *, seller: Seller) -> None:
  """Зафиксировать начисление в момент первой печати FBS-стикера в CRM."""
  from apps.sellers.services.liter_billing import record_shipment_liter_charge_for_order
  from apps.sellers.services.unit_billing import record_shipment_unit_charge_for_order

  charge_date = timezone.localtime(timezone.now()).date()
  record_shipment_liter_charge_for_order(order, seller=seller, charge_date=charge_date)
  record_shipment_unit_charge_for_order(order, seller=seller, charge_date=charge_date)


def load_weekly_shipped_orders(seller: Seller, *, weeks: int = SHIPMENTS_WEEKS_HISTORY) -> dict:
  """
  Заказы с напечатанным FBS-стикером в CRM — по зафиксированному факту печати,
  без зависимости от текущих остатков и наличия Product/StockOperation.
  """
  today = today_local()
  current_week_start, current_week_end = calendar_week_bounds(today)
  oldest_week_start, _ = calendar_week_bounds_offset(weeks - 1, today)

  daily_counts: dict[date, int] = defaultdict(int)
  daily_amounts: dict[date, Decimal] = defaultdict(lambda: Decimal("0"))

  price_by_barcode = _barcode_price_map(seller)
  fallback_tariff = _seller_fallback_tariff(seller)
  match_ids = (
    get_billing_warehouse_match_ids(seller)
    if seller_has_warehouse_config(seller)
    else None
  )

  for event in _iter_sticker_print_events(
    seller,
    oldest_week_start=oldest_week_start,
    current_week_end=current_week_end,
  ):
    if not _order_eligible_for_billing(
      seller,
      event.meta,
      match_ids=match_ids,
      wb_order_id=event.wb_order_id,
    ):
      continue

    daily_counts[event.event_date] += 1
    if event.amount is not None:
      daily_amounts[event.event_date] += event.amount
    else:
      unit_price = _resolve_unit_price(
        event.meta,
        price_by_barcode=price_by_barcode,
        fallback_tariff=fallback_tariff,
      )
      if unit_price is not None:
        daily_amounts[event.event_date] += unit_price

  print_days_per_week: dict[date, int] = defaultdict(int)
  for op_date, count in daily_counts.items():
    if count > 0:
      print_days_per_week[_week_start_for(op_date)] += 1

  weeks_data = [
    _build_week_payload(
      *calendar_week_bounds_offset(weeks_ago, today),
      daily_counts=daily_counts,
      daily_amounts=daily_amounts,
      supplies_per_week=print_days_per_week,
      today=today,
    )
    for weeks_ago in range(weeks)
  ]

  return {
    "today": today.isoformat(),
    "weeks": weeks_data,
  }
