from django.db import transaction

from apps.integrations.models import AuditLog
from apps.integrations.tasks import sync_wb_stocks
from apps.sellers.models import Seller

from apps.warehouse.models import Cell, Product, StockOperation


class IntakeError(Exception):
  pass


def _assign_cell(cell_mode: str, cell_id: int | None) -> Cell:
  if cell_mode == "manual":
    if not cell_id:
      raise IntakeError("Укажите ячейку для нового товара")
    try:
      cell = Cell.objects.select_for_update().get(pk=cell_id)
    except Cell.DoesNotExist as exc:
      raise IntakeError("Ячейка не найдена") from exc
    return cell

  cell = (
    Cell.objects.select_for_update()
    .filter(is_occupied=False)
    .order_by("number")
    .first()
  )
  if not cell:
    raise IntakeError("Нет свободных ячеек")
  return cell


@transaction.atomic
def perform_intake(
  *,
  seller: Seller,
  barcode: str,
  quantity: int,
  user,
  cell_mode: str = "auto",
  cell_id: int | None = None,
  name: str = "",
) -> Product:
  if quantity <= 0:
    raise IntakeError("Количество должно быть больше 0")

  barcode = barcode.strip()
  if not barcode:
    raise IntakeError("Баркод не может быть пустым")

  product = (
    Product.objects.select_for_update()
    .filter(seller=seller, barcode=barcode)
    .select_related("cell", "seller")
    .first()
  )

  if product:
    product.quantity += quantity
    product.save(update_fields=["quantity", "updated_at"])
    is_new = False
  else:
    cell = _assign_cell(cell_mode, cell_id)
    if not cell.is_occupied:
      cell.is_occupied = True
      cell.save(update_fields=["is_occupied"])

    product = Product.objects.create(
      seller=seller,
      barcode=barcode,
      name=name.strip(),
      cell=cell,
      quantity=quantity,
    )
    is_new = True

  StockOperation.objects.create(
    product=product,
    operation_type=StockOperation.OperationType.INTAKE,
    quantity=quantity,
    performed_by=user,
    comment="Новый товар" if is_new else "Приёмка существующего",
  )

  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.INTAKE,
    message=f"Приёмка {quantity} шт., баркод {barcode}",
    details={
      "barcode": barcode,
      "quantity": quantity,
      "cell": product.cell.number,
      "is_new_product": is_new,
    },
  )

  transaction.on_commit(lambda: sync_wb_stocks.delay(seller.id))

  return product
