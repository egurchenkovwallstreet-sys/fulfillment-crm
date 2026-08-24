from django.db import transaction
from django.db.models import Q, QuerySet

from apps.orders.models import Order, PickListItem
from apps.warehouse.models import Cell, Product


def force_delete_cells(cells: QuerySet[Cell]) -> dict[str, int]:
  """Удалить ячейки вместе с привязанными товарами (обход PROTECT в админке)."""
  cell_ids = list(cells.values_list("pk", flat=True))
  if not cell_ids:
    return {"cells": 0, "products": 0, "pick_list_items": 0, "orders_unlinked": 0}

  product_ids = list(Product.objects.filter(cell_id__in=cell_ids).values_list("pk", flat=True))

  with transaction.atomic():
    pick_items_qs = PickListItem.objects.filter(
      Q(cell_id__in=cell_ids) | Q(product_id__in=product_ids),
    )
    pick_list_items = pick_items_qs.count()
    pick_items_qs.delete()

    orders_unlinked = 0
    if product_ids:
      orders_unlinked = Order.objects.filter(product_id__in=product_ids).update(product=None)
      products_deleted, _ = Product.objects.filter(pk__in=product_ids).delete()
    else:
      products_deleted = 0

    cells_deleted, _ = Cell.objects.filter(pk__in=cell_ids).delete()

  return {
    "cells": cells_deleted,
    "products": products_deleted,
    "pick_list_items": pick_list_items,
    "orders_unlinked": orders_unlinked,
  }
