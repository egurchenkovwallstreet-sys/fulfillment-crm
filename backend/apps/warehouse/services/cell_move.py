"""Перенос товара в другую ячейку."""
from __future__ import annotations

from django.db import transaction

from apps.integrations.models import AuditLog
from apps.warehouse.models import Cell, Product, StockOperation
from apps.warehouse.services.cells import refresh_cell_occupied


class CellMoveError(Exception):
  pass


@transaction.atomic
def move_product_to_cell(*, product: Product, new_cell_id: int, user) -> Product:
  if product.cell_id == new_cell_id:
    raise CellMoveError("Товар уже в этой ячейке")

  try:
    new_cell = Cell.objects.select_for_update().get(pk=new_cell_id, seller_id=product.seller_id)
  except Cell.DoesNotExist as exc:
    raise CellMoveError("Ячейка не найдена у этого селлера") from exc

  other_in_cell = (
    Product.objects.select_for_update()
    .filter(cell=new_cell)
    .exclude(pk=product.pk)
    .exists()
  )
  if other_in_cell:
    raise CellMoveError("В выбранной ячейке уже другой товар")

  old_cell = product.cell
  old_number = old_cell.number
  product.cell = new_cell
  product.save(update_fields=["cell", "updated_at"])

  refresh_cell_occupied(old_cell)
  refresh_cell_occupied(new_cell)

  StockOperation.objects.create(
    product=product,
    operation_type=StockOperation.OperationType.ADJUSTMENT,
    quantity=0,
    performed_by=user,
    comment=f"Перенос: №{old_number} → №{new_cell.number}",
  )

  AuditLog.objects.create(
    user=user,
    seller=product.seller,
    action_type=AuditLog.ActionType.INTAKE,
    message=f"Перенос товара {product.barcode}: ячейка №{old_number} → №{new_cell.number}",
    details={
      "product_id": product.id,
      "barcode": product.barcode,
      "from_cell": old_number,
      "to_cell": new_cell.number,
    },
  )

  product.refresh_from_db()
  return product
