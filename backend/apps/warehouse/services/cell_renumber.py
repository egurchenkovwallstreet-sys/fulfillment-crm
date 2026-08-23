"""Перенумерация ячеек селлера без дыр (1, 2, 3…)."""
from __future__ import annotations

from django.db import transaction
from django.db.models import IntegerField
from django.db.models.functions import Cast

from apps.sellers.models import Seller
from apps.warehouse.models import Cell
from apps.warehouse.services.cells import cells_queryset_ordered


@transaction.atomic
def compact_cell_numbers(seller: Seller) -> int:
  """Сжать номера занятых ячеек. Возвращает число обновлённых ячеек."""
  occupied = list(
    cells_queryset_ordered(
      Cell.objects.filter(seller=seller, is_occupied=True).select_for_update()
    )
  )
  if not occupied:
    return 0

  temp_offset = 1_000_000
  for idx, cell in enumerate(occupied):
    cell.number = str(temp_offset + idx)
    cell.save(update_fields=["number"])

  updated = 0
  for idx, cell in enumerate(occupied, start=1):
    cell.number = str(idx)
    cell.save(update_fields=["number"])
    updated += 1

  empty_cells = Cell.objects.filter(seller=seller, is_occupied=False)
  if empty_cells.exists():
    empty_cells.delete()

  return updated
