"""Месячный отчёт по отгруженным поставкам WB для кабинета владельца."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from django.db.models import Min, Prefetch, Q
from django.utils import timezone

from apps.accounts.models import Fulfillment
from apps.integrations.marketplace import WB
from apps.orders.models import OffCrmShipment, Order, Supply
from apps.orders.services.assembly import format_sticker_number, get_wb_stage_label
from apps.orders.services.wb_status import (
  CANCEL_SUPPLIER_STATUSES,
  CANCEL_WB_STATUSES,
  WB_STATUS_AFTER_DELIVER,
  get_wb_status_label,
  is_wb_cancelled,
  order_accepted_at_wb_sc,
  order_reached_wb_sc,
)
from apps.sellers.models import ExcludedSellerWarehouse, Seller, SellerWarehouse
from apps.sellers.services.calendar_periods import calendar_month_start, previous_month_bounds, today_local

BUYER_CANCEL_WB_STATUSES = frozenset({"canceled_by_client", "declined_by_client"})
CARRIER_CANCEL_WB_STATUSES = frozenset({"canceled_by_carrier", "cancel_carrier"})


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


def order_is_cancelled(order: Order) -> bool:
  return order.status == Order.Status.CANCELLED or is_wb_cancelled(
    order.wb_supplier_status or "",
    order.wb_status or "",
  )


def resolve_wb_sorted_at(order: Order, supply: Supply) -> datetime | None:
  if order.wb_sorted_at:
    return order.wb_sorted_at
  if order.status == Order.Status.SHIPPED and order.in_delivery_at:
    return order.in_delivery_at
  return None


def order_sticker_display(order: Order) -> str:
  number = format_sticker_number(order)
  scan_code = (order.sticker_scan_code or "").strip()
  if number and scan_code and scan_code not in number:
    return f"{number} · {scan_code}"
  return number or scan_code or "—"


def off_crm_sticker_display(row: OffCrmShipment) -> str:
  number = (row.sticker_number or "").strip()
  if not number and row.sticker_part_a and row.sticker_part_b:
    number = f"{row.sticker_part_a} / {row.sticker_part_b}"
  if row.crm_order_id:
    crm_sticker = order_sticker_display(row.crm_order)
    if crm_sticker != "—":
      return crm_sticker
  return number or "—"


def _sticker_search_blob(*parts: str) -> str:
  return " ".join((part or "").strip().lower() for part in parts if (part or "").strip())


def order_matches_sticker_query(order: Order, query: str) -> bool:
  token = (query or "").strip().lower()
  if not token:
    return True
  blob = _sticker_search_blob(
    order.sticker_part_a,
    order.sticker_part_b,
    order.sticker_scan_code,
    format_sticker_number(order),
    str(order.wb_order_id),
    order.barcode,
  )
  return token in blob


def off_crm_matches_sticker_query(row: OffCrmShipment, query: str) -> bool:
  token = (query or "").strip().lower()
  if not token:
    return True
  blob = _sticker_search_blob(
    row.sticker_part_a,
    row.sticker_part_b,
    row.sticker_number,
    str(row.wb_order_id),
    row.barcode,
  )
  if row.crm_order_id:
    blob = f"{blob} {_sticker_search_blob(order_sticker_display(row.crm_order))}"
  return token in blob


def wb_sc_acceptance_label(order: Order, supply: Supply) -> str:
  """Человекочитаемый статус приёмки заказа на СЦ WB."""
  sorted_at = resolve_wb_sorted_at(order, supply)
  cancelled = order_is_cancelled(order)
  wb = (order.wb_status or "").strip()

  if sorted_at or order_reached_wb_sc(order):
    if cancelled:
      return "Был отгружен на СЦ WB"
    label = get_wb_status_label(wb)
    return label if label not in ("—", wb, "") else "Отсортирован на СЦ WB"

  if order.in_delivery_at:
    if cancelled:
      return "Передан в доставку · не отсортирован"
    if wb == WB_STATUS_AFTER_DELIVER or not wb:
      return "Не принят · ждёт сортировки"

  if cancelled:
    return "Не отгружен на СЦ WB"

  if order_accepted_at_wb_sc(order):
    label = get_wb_status_label(wb)
    return label if label not in ("—", "") else "Принят на СЦ WB"
  if wb == WB_STATUS_AFTER_DELIVER or wb == "":
    return "Не принят · ждёт сортировки"
  return get_wb_status_label(wb)


def _seller_cancel_where(order: Order, supply: Supply, *, via_crm: bool) -> str:
  if not via_crm or not order.has_sticker:
    return "в ЛК WB (вне CRM)"
  if order.in_delivery_at:
    return "после передачи в доставку"
  if supply.status in (Supply.Status.FORMING, Supply.Status.READY):
    return "в поставке до доставки"
  if order.status in (
    Order.Status.IN_PICKING,
    Order.Status.ASSEMBLED,
    Order.Status.LABEL_PRINTED,
    Order.Status.MARKED,
  ) or order.has_sticker:
    return "на сборке в CRM"
  return "до поставки"


def describe_order_cancellation(
  order: Order,
  supply: Supply,
  *,
  via_crm: bool = True,
) -> dict:
  """Кто отменил и (для селлера) на каком этапе — человекочитаемые подписи."""
  supplier = (order.wb_supplier_status or "").strip()
  wb = (order.wb_status or "").strip()
  empty = {
    "is_cancelled": False,
    "cancel_party": "",
    "cancel_party_label": "—",
    "cancel_where_label": "",
    "cancel_detail_label": "—",
  }
  if not order_is_cancelled(order):
    return empty

  wb_label = get_wb_status_label(wb)
  supplier_label = get_wb_stage_label(supplier)

  if wb in BUYER_CANCEL_WB_STATUSES:
    detail = wb_label if wb_label not in ("—", wb) else "Отменён покупателем"
    return {
      "is_cancelled": True,
      "cancel_party": "buyer",
      "cancel_party_label": "Покупатель",
      "cancel_where_label": "",
      "cancel_detail_label": detail,
    }

  if supplier in CARRIER_CANCEL_WB_STATUSES or wb in CARRIER_CANCEL_WB_STATUSES:
    detail = wb_label if wb_label not in ("—", wb) else supplier_label
    if detail in ("—", supplier):
      detail = "Отменён перевозчиком"
    return {
      "is_cancelled": True,
      "cancel_party": "carrier",
      "cancel_party_label": "Перевозчик",
      "cancel_where_label": "",
      "cancel_detail_label": detail,
    }

  if supplier in CANCEL_SUPPLIER_STATUSES or wb in CANCEL_WB_STATUSES:
    where = _seller_cancel_where(order, supply, via_crm=via_crm)
    detail = supplier_label if supplier_label not in ("—", supplier) else "Отменён"
    return {
      "is_cancelled": True,
      "cancel_party": "seller",
      "cancel_party_label": "Селлер",
      "cancel_where_label": where,
      "cancel_detail_label": f"Селлер · {where}" if where else detail,
    }

  return {
    "is_cancelled": True,
    "cancel_party": "unknown",
    "cancel_party_label": "Отменён",
    "cancel_where_label": "",
    "cancel_detail_label": wb_label if wb_label not in ("—", wb) else "Отменён",
  }


def _serialize_crm_order(order: Order, supply: Supply) -> dict:
  supplier = (order.wb_supplier_status or "").strip()
  wb = (order.wb_status or "").strip()
  cancel = describe_order_cancellation(order, supply, via_crm=True)
  sorted_at = resolve_wb_sorted_at(order, supply)
  return {
    "wb_order_id": order.wb_order_id,
    "barcode": order.barcode,
    "sticker_number": order_sticker_display(order),
    "wb_created_at": order.wb_created_at.isoformat() if order.wb_created_at else None,
    "supply_scanned_at": supply.wb_scanned_at.isoformat() if supply.wb_scanned_at else None,
    "wb_sorted_at": sorted_at.isoformat() if sorted_at else None,
    "was_shipped_to_wb_sc": bool(sorted_at or order_reached_wb_sc(order)),
    "crm_status": order.status,
    "crm_status_label": order.get_status_display(),
    "wb_stage_label": get_wb_stage_label(supplier),
    "wb_status_label": get_wb_status_label(wb),
    "wb_acceptance_label": wb_sc_acceptance_label(order, supply),
    "in_delivery_at": order.in_delivery_at.isoformat() if order.in_delivery_at else None,
    "via_crm": bool(order.has_sticker or order.in_delivery_at),
    **cancel,
  }


def _serialize_off_crm_row(row: OffCrmShipment, supply: Supply) -> dict:
  order = row.crm_order
  if order:
    cancel = describe_order_cancellation(order, supply, via_crm=False)
    wb_acceptance = wb_sc_acceptance_label(order, supply)
    wb_stage_label = get_wb_stage_label(order.wb_supplier_status or "")
    wb_status_label = get_wb_status_label(order.wb_status or "")
    sorted_at = resolve_wb_sorted_at(order, supply)
    wb_created_at = order.wb_created_at.isoformat() if order.wb_created_at else None
    was_shipped = bool(sorted_at or order_reached_wb_sc(order))
  else:
    cancel = {
      "is_cancelled": False,
      "cancel_party": "",
      "cancel_party_label": "—",
      "cancel_where_label": "",
      "cancel_detail_label": "—",
    }
    wb_acceptance = "—"
    wb_stage_label = "—"
    wb_status_label = "—"
    sorted_at = None
    wb_created_at = None
    was_shipped = False

  return {
    "wb_order_id": row.wb_order_id,
    "barcode": row.barcode,
    "sticker_number": off_crm_sticker_display(row),
    "wb_created_at": wb_created_at,
    "supply_scanned_at": supply.wb_scanned_at.isoformat() if supply.wb_scanned_at else None,
    "wb_sorted_at": sorted_at.isoformat() if sorted_at else None,
    "was_shipped_to_wb_sc": was_shipped,
    "resolution_status": row.status,
    "resolution_status_label": row.get_status_display(),
    "wb_stage_label": wb_stage_label,
    "wb_status_label": wb_status_label,
    "wb_acceptance_label": wb_acceptance,
    "shipped_at": row.shipped_at.isoformat() if row.shipped_at else None,
    "detected_at": row.detected_at.isoformat() if row.detected_at else None,
    "warehouse_name": row.warehouse_name or "—",
    **cancel,
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
  sticker_query: str | None = None,
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
      Prefetch(
        "orders",
        queryset=Order.objects.order_by("wb_order_id"),
      ),
    )
    .annotate(crm_delivered_at_agg=Min("orders__in_delivery_at"))
    .order_by("-crm_delivered_at_agg", "-wb_scanned_at", "-created_at")
  )

  off_crm_by_supply: dict[tuple[int, str], list[OffCrmShipment]] = {}
  for row in OffCrmShipment.objects.filter(seller_id__in=seller_ids).select_related("crm_order").exclude(wb_supply_id=""):
    key = (row.seller_id, row.wb_supply_id)
    off_crm_by_supply.setdefault(key, []).append(row)

  rows: list[dict] = []
  total_crm = 0
  total_off = 0

  for supply in supplies:
    orders = list(supply.orders.all())
    crm_orders = list(orders)
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

    if sticker_query:
      crm_orders = [order for order in crm_orders if order_matches_sticker_query(order, sticker_query)]
      off_crm_in_month = [
        row for row in off_crm_in_month if off_crm_matches_sticker_query(row, sticker_query)
      ]
      if not crm_orders and not off_crm_in_month:
        continue

    crm_payload = [_serialize_crm_order(order, supply) for order in crm_orders]
    off_payload = [_serialize_off_crm_row(row, supply) for row in off_crm_in_month]
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
    "sticker_query": (sticker_query or "").strip() or None,
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
