"""Ячейки селлера — нумерация с 1 по возрастанию для каждого селлера."""
from django.db.models import IntegerField, Max, QuerySet
from django.db.models.functions import Cast

from apps.sellers.models import Seller
from apps.warehouse.models import Cell


def cells_queryset_ordered(qs: QuerySet | None = None) -> QuerySet:
  base = qs if qs is not None else Cell.objects.all()
  return base.annotate(
    number_sort=Cast("number", IntegerField()),
  ).order_by("number_sort")


def _next_cell_number(seller: Seller) -> str:
  agg = (
    Cell.objects.filter(seller=seller)
    .annotate(number_sort=Cast("number", IntegerField()))
    .aggregate(max_num=Max("number_sort"))
  )
  max_num = agg.get("max_num") or 0
  return str(max_num + 1)


def first_free_cell(seller: Seller) -> Cell:
  """Свободная ячейка селлера или новая с следующим номером."""
  free = (
    cells_queryset_ordered(Cell.objects.filter(seller=seller, is_occupied=False))
    .select_for_update()
    .first()
  )
  if free:
    return free

  return Cell.objects.create(
    seller=seller,
    number=_next_cell_number(seller),
    is_occupied=False,
  )


def refresh_cell_occupied(cell: Cell) -> None:
  """Синхронизировать флаг is_occupied с фактическими товарами в ячейке."""
  occupied = cell.products.exists()
  if cell.is_occupied != occupied:
    cell.is_occupied = occupied
    cell.save(update_fields=["is_occupied"])
