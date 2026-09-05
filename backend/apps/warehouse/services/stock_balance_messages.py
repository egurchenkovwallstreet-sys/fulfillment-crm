"""Тексты сводки по остаткам для UI."""
from __future__ import annotations


def stock_balance_breakdown_message(
  *,
  crm_quantity_before: int,
  crm_quantity_after: int,
  reserved_new_orders: int,
  wb_target_quantity: int,
  verified: bool,
  restock_required: bool = False,
  physical_quantity: int | None = None,
  intake_quantity: int | None = None,
) -> str:
  parts = [
    f"CRM: было {crm_quantity_before} → стало {crm_quantity_after} шт.",
    f"«Новые»: {reserved_new_orders} шт.",
    f"ЛК WB: {wb_target_quantity} шт.",
  ]
  if physical_quantity is not None:
    parts.insert(0, f"Насчитано на полке: {physical_quantity} шт.")
  if intake_quantity is not None:
    parts.insert(0, f"Принято сейчас: +{intake_quantity} шт.")
  if restock_required:
    parts.append(
      "Недостаточно товара — необходимо догрузить. В ЛК WB установлен 0."
    )
  if not verified:
    parts.append("Сверка с ЛК WB: расхождение — проверьте и нажмите «Готово».")
  elif not restock_required:
    parts.append("Сверка с ЛК WB: OK.")
  return " · ".join(parts)
