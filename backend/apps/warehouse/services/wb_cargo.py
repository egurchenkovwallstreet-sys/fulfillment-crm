"""Типы груза WB: склад FBS ↔ карточка товара."""
from __future__ import annotations

from apps.sellers.models import Seller, SellerWarehouse

CARGO_TYPE_LABELS: dict[int, str] = {
  1: "МГТ (малогабарит)",
  2: "СГТ (сверхгабарит)",
  3: "КГТ+ (крупногабарит)",
}

DELIVERY_TYPE_LABELS: dict[int, str] = {
  1: "FBS",
  2: "DBS",
  3: "DBW",
  5: "С&C",
  6: "EDBS",
}


def parse_wb_int(raw) -> int | None:
  if raw is None or raw == "":
    return None
  try:
    return int(raw)
  except (TypeError, ValueError):
    return None


def cargo_type_label(value: int | None) -> str:
  if not value:
    return "тип не указан"
  return CARGO_TYPE_LABELS.get(value, f"тип {value}")


def delivery_type_label(value: int | None) -> str:
  if not value:
    return "FBS"
  return DELIVERY_TYPE_LABELS.get(value, f"тип {value}")


def warehouse_option_label(warehouse: SellerWarehouse) -> str:
  name = warehouse.name or f"Склад #{warehouse.wb_warehouse_id}"
  cargo = cargo_type_label(warehouse.cargo_type)
  delivery = delivery_type_label(warehouse.delivery_type)
  if warehouse.delivery_type not in (None, 1):
    return f"{name} · {delivery} · {cargo}"
  return f"{name} · {cargo}"


def seller_warehouse_alternatives_text(
  seller: Seller,
  *,
  current: SellerWarehouse,
) -> str:
  others = list(
    SellerWarehouse.objects.filter(seller=seller, is_enabled=True)
    .exclude(pk=current.pk)
    .order_by("name", "wb_warehouse_id")
  )
  if not others:
    return (
      " У селлера в CRM нет других включённых складов. "
      "Создайте подходящий FBS-склад в ЛК WB и нажмите «Загрузить из WB»."
    )
  parts = [warehouse_option_label(wh) for wh in others]
  return " Попробуйте другой склад селлера: " + "; ".join(parts) + "."


def assert_fbs_warehouse_for_stocks(warehouse: SellerWarehouse) -> None:
  if warehouse.delivery_type is None or warehouse.delivery_type == 1:
    return
  name = warehouse.name or f"склад #{warehouse.wb_warehouse_id}"
  raise ValueError(
    f"Склад «{name}» — {delivery_type_label(warehouse.delivery_type)}, "
    "не FBS. Остатки через CRM выставляются только на FBS-склады."
  )
