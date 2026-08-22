from dataclasses import dataclass

from django.db import transaction

from apps.integrations.models import AuditLog
from apps.sellers.models import Seller

from apps.warehouse.models import Cell, Product, StockOperation
from apps.warehouse.services.cell_label import build_cell_label_data
from apps.warehouse.services.cells import first_free_cell, refresh_cell_occupied
from apps.warehouse.services.marking_lookup import lookup_marking_for_barcode
from apps.warehouse.services.wb_stocks import (
  STOCK_MODE_INTAKE,
  STOCK_MODE_SYNC_FROM_WB,
  WBStockError,
  fetch_wb_stock_for_barcode,
  get_seller_warehouse,
  push_wb_stock_increment,
)


class IntakeError(Exception):
  pass


@dataclass
class IntakeResult:
  product: Product
  print_cell_label: bool
  cell_label: dict[str, str] | None
  stock_mode: str
  wb_sync: dict | None = None


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
  wb_warehouse_id: int,
  stock_mode: str = STOCK_MODE_INTAKE,
  verified_stock_match: bool = False,
  cell_mode: str = "auto",
  cell_id: int | None = None,
  name: str = "",
) -> IntakeResult:
  try:
    warehouse = get_seller_warehouse(seller, wb_warehouse_id)
  except WBStockError as exc:
    raise IntakeError(str(exc)) from exc

  barcode = barcode.strip()
  if not barcode:
    raise IntakeError("Баркод не может быть пустым")

  wb_sync: dict | None = None
  intake_quantity = quantity

  if stock_mode == STOCK_MODE_SYNC_FROM_WB:
    if not verified_stock_match:
      raise IntakeError(
        "Подтвердите, что на фулфилменте пересчитали остатки и они совпадают с ЛК WB"
      )
    try:
      wb_amount = fetch_wb_stock_for_barcode(seller, warehouse, barcode)
    except WBStockError as exc:
      raise IntakeError(str(exc)) from exc
    intake_quantity = wb_amount
    wb_sync = {
      "mode": stock_mode,
      "wb_warehouse_id": warehouse.wb_warehouse_id,
      "warehouse_name": warehouse.name,
      "wb_amount": wb_amount,
      "verified_stock_match": True,
    }
  else:
    if intake_quantity <= 0:
      raise IntakeError("Количество должно быть больше 0")

  product = (
    Product.objects.select_for_update()
    .filter(seller=seller, barcode=barcode)
    .select_related("cell", "seller")
    .first()
  )

  if stock_mode == STOCK_MODE_SYNC_FROM_WB:
    if product:
      product.quantity = intake_quantity
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
        quantity=intake_quantity,
        requires_marking=marking.requires_marking if marking.wb_found else False,
      )
      refresh_cell_occupied(cell)
      is_new = True
  elif product:
    product.quantity += intake_quantity
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
      quantity=intake_quantity,
      requires_marking=marking.requires_marking if marking.wb_found else False,
    )
    refresh_cell_occupied(cell)
    is_new = True

  comment = (
    f"Сверка с WB, склад {warehouse.name or warehouse.wb_warehouse_id}: "
    f"остаток CRM = {intake_quantity} шт. (подтверждено менеджером)"
    if stock_mode == STOCK_MODE_SYNC_FROM_WB
    else f"Приёмка +{intake_quantity} шт., склад WB {warehouse.name or warehouse.wb_warehouse_id}"
  )

  StockOperation.objects.create(
    product=product,
    operation_type=StockOperation.OperationType.INTAKE
    if stock_mode == STOCK_MODE_INTAKE
    else StockOperation.OperationType.ADJUSTMENT,
    quantity=intake_quantity if stock_mode == STOCK_MODE_INTAKE else intake_quantity,
    performed_by=user,
    comment=comment,
  )

  if stock_mode == STOCK_MODE_INTAKE:
    try:
      wb_sync = push_wb_stock_increment(seller, warehouse, barcode, intake_quantity)
    except WBStockError as exc:
      raise IntakeError(str(exc)) from exc

  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.INTAKE,
    message=(
      f"Приёмка {intake_quantity} шт., баркод {barcode}, "
      f"склад WB {warehouse.name or warehouse.wb_warehouse_id}"
    ),
    details={
      "barcode": barcode,
      "quantity": intake_quantity,
      "cell": product.cell.number,
      "is_new_product": is_new,
      "requires_marking": product.requires_marking,
      "stock_mode": stock_mode,
      "wb_warehouse_id": warehouse.wb_warehouse_id,
      "wb_sync": wb_sync,
      "verified_stock_match": verified_stock_match,
    },
  )

  cell_label = build_cell_label_data(product) if is_new else None
  return IntakeResult(
    product=product,
    print_cell_label=is_new,
    cell_label=cell_label,
    stock_mode=stock_mode,
    wb_sync=wb_sync,
  )
