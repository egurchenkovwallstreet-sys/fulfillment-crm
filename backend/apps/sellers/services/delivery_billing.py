"""Биллинг и график отгрузок — по факту передачи в доставку с обслуживаемых FBS-складов."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from apps.integrations.marketplace import WB
from apps.orders.models import OffCrmShipment, Order, Supply
from apps.sellers.models import Seller, ShipmentUnitCharge
from apps.sellers.services.calendar_periods import (
  calendar_week_bounds,
  calendar_week_bounds_offset,
  today_local,
)
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
  get_enabled_wb_warehouse_ids,
  get_enabled_warehouse_match_ids,
  order_matches_enabled_warehouse,
  seller_has_warehouse_config,
)


@dataclass(frozen=True)
class _DeliveryEvent:
  wb_order_id: int
  event_date: date
  amount: Decimal | None
  meta: _ShippedOrderMeta | None
  supply_id: int | None = None


def _meta_for_order(order: Order) -> _ShippedOrderMeta:
  return _ShippedOrderMeta(
    barcode=str(order.barcode or "").strip(),
    warehouse_id=order.wb_warehouse_id,
  )


def _order_on_serviced_warehouse(seller: Seller, order: Order, *, match_ids: set[int] | None) -> bool:
  if not seller_has_warehouse_config(seller):
    return True
  match_ids = match_ids if match_ids is not None else get_enabled_warehouse_match_ids(seller)
  if not match_ids:
    return False
  return order_matches_enabled_warehouse(
    seller,
    order.wb_warehouse_id,
    None,
    match_ids=match_ids,
  )


def _off_crm_on_serviced_warehouse(seller: Seller, row: OffCrmShipment, *, match_ids: set[int] | None) -> bool:
  if not seller_has_warehouse_config(seller):
    return True
  enabled = get_enabled_wb_warehouse_ids(seller)
  if not enabled:
    return False
  wh_id = row.wb_warehouse_id
  return wh_id is not None and int(wh_id) in enabled


def record_billing_on_order_delivery(order: Order, *, seller: Seller | None = None) -> None:
  """Зафиксировать начисление в момент передачи заказа в доставку (один раз на wb_order_id)."""
  seller = seller or order.seller
  if order.in_delivery_at is None:
    return
  if not _order_on_serviced_warehouse(seller, order, match_ids=None):
    return

  from apps.sellers.services.liter_billing import record_shipment_liter_charge_for_order
  from apps.sellers.services.unit_billing import record_shipment_unit_charge_for_order

  charge_date = timezone.localtime(order.in_delivery_at).date()
  record_shipment_liter_charge_for_order(order, seller=seller, charge_date=charge_date)
  record_shipment_unit_charge_for_order(order, seller=seller, charge_date=charge_date)


def record_billing_for_off_crm_shipment(shipment: OffCrmShipment) -> None:
  """Начисление за отгрузку через ЛК WB (после списания с нашего склада)."""
  seller = shipment.seller
  if not _off_crm_on_serviced_warehouse(seller, shipment, match_ids=None):
    return
  if not shipment.wb_order_id:
    return

  from apps.sellers.services.unit_billing import record_shipment_unit_charge_for_order

  order = shipment.crm_order
  if order is None:
    order = Order.objects.filter(seller=seller, wb_order_id=shipment.wb_order_id).first()
  charge_date = timezone.localtime(shipment.shipped_at or timezone.now()).date()
  if order is not None:
    if order.in_delivery_at is None:
      order.in_delivery_at = shipment.shipped_at or timezone.now()
      order.save(update_fields=["in_delivery_at", "updated_at"])
    record_billing_on_order_delivery(order, seller=seller)
    return

  barcode = (shipment.barcode or "").strip()
  if ShipmentUnitCharge.objects.filter(seller=seller, wb_order_id=int(shipment.wb_order_id)).exists():
    return
  from apps.sellers.services.unit_billing import _unit_price_for_barcode

  unit_price = _unit_price_for_barcode(seller, barcode, marketplace=WB)
  if unit_price is None:
    return
  ShipmentUnitCharge.objects.create(
    seller=seller,
    product=None,
    barcode=barcode,
    marketplace=WB,
    order=None,
    wb_order_id=int(shipment.wb_order_id),
    charge_date=charge_date,
    quantity=1,
    unit_price=unit_price,
    amount=unit_price,
  )


def _charge_amounts_by_wb_order(seller: Seller, wb_order_ids: set[int]) -> dict[int, Decimal]:
  if not wb_order_ids:
    return {}
  return {
    int(row["wb_order_id"]): row["amount"]
    for row in ShipmentUnitCharge.objects.filter(
      seller=seller,
      marketplace=WB,
      wb_order_id__in=wb_order_ids,
    ).values("wb_order_id", "amount")
  }


def _iter_delivery_events(
  seller: Seller,
  *,
  oldest_week_start: date,
  current_week_end: date,
) -> list[_DeliveryEvent]:
  """Уникальные заказы WB: переданы в доставку с обслуживаемых складов."""
  events: list[_DeliveryEvent] = []
  seen_wb_order_ids: set[int] = set()
  match_ids = get_enabled_warehouse_match_ids(seller) if seller_has_warehouse_config(seller) else None

  delivery_orders = Order.objects.filter(
    seller=seller,
    wb_order_id__isnull=False,
    in_delivery_at__isnull=False,
    in_delivery_at__date__gte=oldest_week_start,
    in_delivery_at__date__lte=current_week_end,
  )
  pending_ids: set[int] = set()
  for order in delivery_orders:
    if not _order_on_serviced_warehouse(seller, order, match_ids=match_ids):
      continue
    pending_ids.add(int(order.wb_order_id))

  off_crm_rows = list(
    OffCrmShipment.objects.filter(
      seller=seller,
      wb_order_id__isnull=False,
      shipped_at__isnull=False,
      shipped_at__date__gte=oldest_week_start,
      shipped_at__date__lte=current_week_end,
    ).exclude(status=OffCrmShipment.Status.SKIPPED),
  )
  for row in off_crm_rows:
    if not _off_crm_on_serviced_warehouse(seller, row, match_ids=match_ids):
      continue
    pending_ids.add(int(row.wb_order_id))

  charge_amounts = _charge_amounts_by_wb_order(seller, pending_ids)

  for order in delivery_orders:
    if not _order_on_serviced_warehouse(seller, order, match_ids=match_ids):
      continue
    wb_order_id = int(order.wb_order_id)
    if wb_order_id in seen_wb_order_ids:
      continue
    seen_wb_order_ids.add(wb_order_id)
    event_date = timezone.localtime(order.in_delivery_at).date()
    supply_id = (
      Supply.objects.filter(orders=order)
      .order_by("-id")
      .values_list("id", flat=True)
      .first()
    )
    events.append(
      _DeliveryEvent(
        wb_order_id=wb_order_id,
        event_date=event_date,
        amount=charge_amounts.get(wb_order_id),
        meta=_meta_for_order(order),
        supply_id=supply_id,
      ),
    )

  for row in off_crm_rows:
    wb_order_id = int(row.wb_order_id)
    if wb_order_id in seen_wb_order_ids:
      continue
    if not _off_crm_on_serviced_warehouse(seller, row, match_ids=match_ids):
      continue
    seen_wb_order_ids.add(wb_order_id)
    events.append(
      _DeliveryEvent(
        wb_order_id=wb_order_id,
        event_date=timezone.localtime(row.shipped_at).date(),
        amount=charge_amounts.get(wb_order_id),
        meta=_ShippedOrderMeta(
          barcode=str(row.barcode or "").strip(),
          warehouse_id=row.wb_warehouse_id,
        ),
        supply_id=None,
      ),
    )

  return events


def _supplies_per_week(
  seller: Seller,
  *,
  oldest_week_start: date,
  current_week_end: date,
) -> dict[date, int]:
  enabled = get_enabled_wb_warehouse_ids(seller)
  if seller_has_warehouse_config(seller) and not enabled:
    return {}

  supply_filter = Q(seller=seller)
  if enabled:
    supply_filter &= Q(wb_warehouse_id__in=enabled)

  week_sets: dict[date, set[int]] = defaultdict(set)
  rows = (
    Supply.objects.filter(supply_filter)
    .filter(
      orders__in_delivery_at__isnull=False,
      orders__in_delivery_at__date__gte=oldest_week_start,
      orders__in_delivery_at__date__lte=current_week_end,
    )
    .values_list("id", "orders__in_delivery_at")
    .distinct()
  )
  for supply_id, in_delivery_at in rows:
    if not in_delivery_at:
      continue
    day = timezone.localtime(in_delivery_at).date()
    week_sets[_week_start_for(day)].add(int(supply_id))

  return {week_start: len(ids) for week_start, ids in week_sets.items()}


def load_weekly_shipped_orders(seller: Seller, *, weeks: int = SHIPMENTS_WEEKS_HISTORY) -> dict:
  """Заказы, переданные в доставку с обслуживаемых FBS-складов (CRM или ЛК WB)."""
  today = today_local()
  current_week_start, current_week_end = calendar_week_bounds(today)
  oldest_week_start, _ = calendar_week_bounds_offset(weeks - 1, today)

  daily_counts: dict[date, int] = defaultdict(int)
  daily_amounts: dict[date, Decimal] = defaultdict(lambda: Decimal("0"))

  price_by_barcode = _barcode_price_map(seller)
  fallback_tariff = _seller_fallback_tariff(seller)
  match_ids = get_enabled_warehouse_match_ids(seller) if seller_has_warehouse_config(seller) else None

  for event in _iter_delivery_events(
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

  supplies_per_week = _supplies_per_week(
    seller,
    oldest_week_start=oldest_week_start,
    current_week_end=current_week_end,
  )

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
