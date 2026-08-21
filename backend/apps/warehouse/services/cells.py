"""Запросы ячеек — номера хранятся строкой, сортировка по числу."""
from django.db.models import IntegerField, QuerySet
from django.db.models.functions import Cast

from apps.warehouse.models import Cell


def cells_queryset_ordered(qs: QuerySet | None = None) -> QuerySet:
  base = qs if qs is not None else Cell.objects.all()
  return base.annotate(
    number_sort=Cast("number", IntegerField()),
  ).order_by("number_sort")


def first_free_cell() -> Cell | None:
  return (
    cells_queryset_ordered(Cell.objects.filter(is_occupied=False))
    .select_for_update()
    .first()
  )


def refresh_cell_occupied(cell: Cell) -> None:
  """Синхронизировать флаг is_occupied с фактическими товарами в ячейке."""
  occupied = cell.products.exists()
  if cell.is_occupied != occupied:
    cell.is_occupied = occupied
    cell.save(update_fields=["is_occupied"])
