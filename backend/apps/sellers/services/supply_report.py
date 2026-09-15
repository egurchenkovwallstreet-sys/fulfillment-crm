"""Месячный отчёт по отгруженным поставкам WB для кабинета владельца."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from django.db.models import Min, Prefetch, Q
from django.utils import timezone

from apps.accounts.models import Fulfillment
from apps.integrations.marketplace import WB
from apps.orders.models import OffCrmShipment, Order, Supply
from apps.sellers.models import ExcludedSellerWarehouse, Seller, SellerWarehouse
from apps.sellers.services.calendar_periods import calendar_month_start, previous_month_bounds, today_local


def parse_report_month(value: str | None) -> date | None:
  if not value:
    return None
  token = value.strip()[:7]
  try:
    year_s, month_s = token.split("-", 1)
    return date(int(year_s), int(month_s), 1)
  except (TypeError, ValueError):
    return None


def month_bounds(month: date) -> tuple[date, date]:
  """Первый и последний день календарного месяца."""
  start = month.replace(day=1)
  if start.month == 12:
    next_month = date(start.year + 1, 1, 1)
  else:
    next_month = date(start.year, start.month + 1, 1)
  end = next_month - timedelta(days=1)
  return start, end


def _format_dt(value: datetime | None) -> str | None:
  if not value:
    return None
  return timezone.localtime(value).strftime("%d.%m.%Y %H:%M")


def _shipment_dates_label(crm_at: datetime | None, scanned_at: datetime | None) -> str:
  left = _format_dt(crm_at) or "—"
  right = _format_dt(scanned_at) or "—"
  return f"{left} / {right}"


def _warehouse_name_maps(seller_ids: list[int]) -> dict[int, dict[int, str]]:
  maps: dict[int, dict[int, str]] = {seller_id: {} for seller_id in seller_ids}
  for seller_id, wh_id, name in SellerWarehouse.objects.filter(
    seller_id__in=seller_ids,
  ).values_list("seller_id", "wb_warehouse_id", "name"):
    if wh_id is not None:
      maps[seller_id][int(wh_id)] = (name or "").strip() or f"Склад #{wh_id}"
  for seller_id, ext_id, name in ExcludedSellerWarehouse.objects.filter(
    seller_id__in=seller_ids,
    marketplace=WB,
  ).values_list("seller_id", "warehouse_external_id", "name"):
    label = (name or "").strip() or f"Склад #{ext_id}"
    maps[seller_id][int(ext_id)] = label
  return maps


def _warehouse_label(
  seller_id: int,
  warehouse_id: int | None,
  maps: dict[int, dict[int, str]],
) -> str:
  if warehouse_id is None:
    return "—"
  return maps.get(seller_id, {}).get(int(warehouse_id), f"Склад #{warehouse_id}")


def _serialize_crm_order(order: Order) -> dict:
  return {
    "wb_order_id": order.wb_order_id,
    "barcode": order.barcode,
    "crm_status": order.status,
    "crm_status_label": order.get_status_display(),
    "wb_supplier_status": order.wb_supplier_status or "",
    "wb_status": order.wb_status or "",
    "in_delivery_at": order.in_delivery_at.isoformat() if order.in_delivery_at else None,
  }


def _serialize_off_crm_row(row: OffCrmShipment) -> dict:
  return {
    "wb_order_id": row.wb_order_id,
    "barcode": row.barcode,
    "resolution_status": row.status,
    "resolution_status_label": row.get_status_display(),
    "shipped_at": row.shipped_at.isoformat() if row.shipped_at else None,
    "detected_at": row.detected_at.isoformat() if row.detected_at else None,
    "warehouse_name": row.warehouse_name or "—",
  }


def _supply_sort_key(row: dict) -> tuple:
  for field in ("crm_delivered_at", "wb_scanned_at"):
    raw = row.get(field)
    if raw:
      try:
        return (0, datetime.fromisoformat(raw))
      except (TypeError, ValueError):
        pass
  return (1, datetime.min.replace(tzinfo=timezone.get_current_timezone()))


def load_supply_report(
  fulfillment: Fulfillment,
  *,
  month: date,
  seller_id: int | None = None,
) -> dict:
  """Собрать отчёт по поставкам за календарный месяц."""
  month_start, month_end = month_bounds(month)
  sellers_qs = Seller.objects.filter(fulfillment=fulfillment).order_by("company_name")
  if seller_id is not None:
    sellers_qs = sellers_qs.filter(pk=seller_id)
  sellers = list(sellers_qs)
  seller_ids = [seller.id for seller in sellers]
  if not seller_ids:
    return {
      "month": month.isoformat(),
      "month_start": month_start.isoformat(),
      "month_end": month_end.isoformat(),
      "supplies": [],
      "totals": {"supplies": 0, "crm_orders": 0, "off_crm_orders": 0},
      "built_at": timezone.now().isoformat(),
    }

  warehouse_maps = _warehouse_name_maps(seller_ids)

  month_filter = Q(
    orders__in_delivery_at__date__gte=month_start,
    orders__in_delivery_at__date__lte=month_end,
  ) | Q(
    wb_scanned_at__date__gte=month_start,
    wb_scanned_at__date__lte=month_end,
  )

  off_crm_supply_ids = list(
    OffCrmShipment.objects.filter(
      seller_id__in=seller_ids,
      wb_supply_id__gt="",
      shipped_at__date__gte=month_start,
      shipped_at__date__lte=month_end,
    )
    .values_list("wb_supply_id", flat=True)
    .distinct()
  )
  if off_crm_supply_ids:
    month_filter |= Q(wb_supply_id__in=off_crm_supply_ids)

  supplies = (
    Supply.objects.filter(seller_id__in=seller_ids)
    .filter(month_filter)
    .distinct()
    .select_related("seller")
    .prefetch_related(
      Prefetch("orders", queryset=Order.objects.order_by("wb_order_id")),
    )
    .annotate(crm_delivered_at_agg=Min("orders__in_delivery_at"))
    .order_by("-crm_delivered_at_agg", "-wb_scanned_at", "-created_at")
  )

  off_crm_by_supply: dict[tuple[int, str], list[OffCrmShipment]] = {}
  for row in OffCrmShipment.objects.filter(seller_id__in=seller_ids).exclude(wb_supply_id=""):
    key = (row.seller_id, row.wb_supply_id)
    off_crm_by_supply.setdefault(key, []).append(row)

  rows: list[dict] = []
  total_crm = 0
  total_off = 0

  for supply in supplies:
    orders = list(supply.orders.all())
    crm_orders = [
      order
      for order in orders
      if order.in_delivery_at is not None and order.has_sticker
    ]
    crm_delivered_at = min(
      (order.in_delivery_at for order in crm_orders if order.in_delivery_at),
      default=supply.crm_delivered_at_agg,
    )
    off_crm_rows = off_crm_by_supply.get((supply.seller_id, supply.wb_supply_id), [])
    off_crm_in_month = [
      row
      for row in off_crm_rows
      if row.shipped_at and month_start <= timezone.localtime(row.shipped_at).date() <= month_end
    ]
    if not crm_orders and not off_crm_in_month and not supply.wb_scanned_at:
      continue
    if crm_delivered_at and not (
      month_start <= timezone.localtime(crm_delivered_at).date() <= month_end
      or (supply.wb_scanned_at and month_start <= timezone.localtime(supply.wb_scanned_at).date() <= month_end)
      or off_crm_in_month
    ):
      continue

    crm_payload = [_serialize_crm_order(order) for order in crm_orders]
    off_payload = [_serialize_off_crm_row(row) for row in off_crm_in_month]
    total_crm += len(crm_payload)
    total_off += len(off_payload)

    rows.append(
      {
        "supply_id": supply.id,
        "wb_supply_id": supply.wb_supply_id or "—",
        "seller_id": supply.seller_id,
        "seller_name": supply.seller.company_name,
        "warehouse_id": supply.wb_warehouse_id,
        "warehouse_name": _warehouse_label(
          supply.seller_id,
          supply.wb_warehouse_id,
          warehouse_maps,
        ),
        "supply_status": supply.status,
        "supply_status_label": supply.get_status_display(),
        "barcode_scanned": supply.wb_scanned_at is not None,
        "crm_delivered_at": crm_delivered_at.isoformat() if crm_delivered_at else None,
        "wb_scanned_at": supply.wb_scanned_at.isoformat() if supply.wb_scanned_at else None,
        "shipment_dates": _shipment_dates_label(crm_delivered_at, supply.wb_scanned_at),
        "crm_orders": crm_payload,
        "off_crm_orders": off_payload,
        "crm_orders_count": len(crm_payload),
        "off_crm_orders_count": len(off_payload),
      }
    )

  rows.sort(key=_supply_sort_key, reverse=True)

  return {
    "month": month.isoformat(),
    "month_start": month_start.isoformat(),
    "month_end": month_end.isoformat(),
    "supplies": rows,
    "totals": {
      "supplies": len(rows),
      "crm_orders": total_crm,
      "off_crm_orders": total_off,
    },
    "built_at": timezone.now().isoformat(),
  }


def months_to_refresh(day: date | None = None) -> list[date]:
  """Текущий и предыдущий календарный месяц — храним снимок без повторного расчёта."""
  day = day or today_local()
  current = calendar_month_start(day)
  previous, _ = previous_month_bounds(day)
  return [previous, current]


def prune_supply_report_snapshots(day: date | None = None) -> int:
  """Удалить снимки старше предыдущего календарного месяца."""
  from apps.sellers.models import SupplyReportSnapshot

  day = day or today_local()
  keep_from, _ = previous_month_bounds(day)
  deleted, _ = SupplyReportSnapshot.objects.filter(month__lt=keep_from).delete()
  return deleted
