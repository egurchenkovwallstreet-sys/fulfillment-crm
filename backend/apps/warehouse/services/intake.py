from dataclasses import dataclass

from django.db import transaction

from apps.integrations.models import AuditLog
from apps.integrations.tasks import sync_wb_stocks
from apps.sellers.models import Seller

from apps.warehouse.models import Cell, Product, StockOperation
from apps.warehouse.services.cell_label import build_cell_label_data
from apps.warehouse.services.cells import first_free_cell, refresh_cell_occupied
from apps.warehouse.services.marking_lookup import lookup_marking_for_barcode


class IntakeError(Exception):
  pass


@dataclass
class IntakeResult:
  product: Product
  print_cell_label: bool
  cell_label: dict[str, str] | None


def _assign_cell(cell_mode: str, cell_id: int | None) -> Cell:
  if cell_mode == "manual":
    if not cell_id:
      raise IntakeError("Укажите ячейку для нового товара")
    try:
      cell = Cell.objects.select_for_update().get(pk=cell_id)
    except Cell.DoesNotExist as exc:
      raise IntakeError("Ячейка не найдена") from exc
    return cell

  cell = first_free_cell()
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
) -> IntakeResult:
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
    marking = lookup_marking_for_barcode(seller, barcode)

    product = Product.objects.create(
      seller=seller,
      barcode=barcode,
      name=name.strip() or marking.title,
      cell=cell,
      quantity=quantity,
      requires_marking=marking.requires_marking if marking.wb_found else False,
    )
    refresh_cell_occupied(cell)
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
      "requires_marking": product.requires_marking,
    },
  )

  transaction.on_commit(lambda: sync_wb_stocks.delay(seller.id))

  cell_label = build_cell_label_data(product) if is_new else None
  return IntakeResult(
    product=product,
    print_cell_label=is_new,
    cell_label=cell_label,
  )
