from dataclasses import dataclass

from django.db import transaction

from apps.integrations.models import AuditLog
from apps.integrations.marketplace import OZON, WB, normalize_marketplace
from apps.sellers.models import Seller

from apps.warehouse.models import Cell, Product, StockOperation
from apps.warehouse.services.cell_label import build_cell_label_data
from apps.warehouse.services.cells import create_cell_with_next_number, first_free_cell, refresh_cell_occupied
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


def _assign_cell(
  seller: Seller,
  cell_mode: str,
  cell_id: int | None,
  marketplace: str = WB,
  *,
  sequential: bool = False,
) -> Cell:
  mp = normalize_marketplace(marketplace)
  if cell_mode == "manual":
    if not cell_id:
      raise IntakeError("Укажите ячейку для нового товара")
    try:
      cell = Cell.objects.select_for_update().get(pk=cell_id, seller=seller, marketplace=mp)
    except Cell.DoesNotExist as exc:
      raise IntakeError("Ячейка не найдена у этого селлера") from exc
    return cell

  if sequential:
    return create_cell_with_next_number(seller, mp)

  return first_free_cell(seller, mp)


@transaction.atomic
def perform_intake(
  *,
  seller: Seller,
  barcode: str,
  quantity: int,
  user,
  wb_warehouse_id: int | None = None,
  stock_mode: str = STOCK_MODE_INTAKE,
  verified_stock_match: bool = False,
  cell_mode: str = "auto",
  cell_id: int | None = None,
  name: str = "",
  marketplace: str = WB,
  sync_variant: str | None = None,
) -> IntakeResult:
  mp = normalize_marketplace(marketplace)
  barcode = barcode.strip()
  if not barcode:
    raise IntakeError("Баркод не может быть пустым")

  warehouse = None
  wb_sync: dict | None = None
  intake_quantity = quantity

  if mp == OZON:
    if stock_mode == STOCK_MODE_SYNC_FROM_WB:
      raise IntakeError("Сверка с ЛК WB недоступна на вкладке Ozon")
    if intake_quantity <= 0:
      raise IntakeError("Количество должно быть больше 0")
  else:
    try:
      warehouse = get_seller_warehouse(seller, wb_warehouse_id)
    except WBStockError as exc:
      raise IntakeError(str(exc)) from exc

    if stock_mode == STOCK_MODE_SYNC_FROM_WB:
      sync_scan = sync_variant == "scan"
      if not sync_scan and not verified_stock_match:
        raise IntakeError(
          "Подтвердите, что на фулфилменте пересчитали остатки и они совпадают с ЛК WB"
        )
      try:
        wb_amount = fetch_wb_stock_for_barcode(seller, warehouse, barcode)
      except WBStockError as exc:
        raise IntakeError(str(exc)) from exc
      if sync_scan and wb_amount < 1:
        raise IntakeError(
          f"Баркод {barcode} не найден в остатках ЛК WB на складе "
          f"«{warehouse.name or warehouse.wb_warehouse_id}»"
        )
      intake_quantity = wb_amount
      wb_sync = {
        "mode": stock_mode,
        "wb_warehouse_id": warehouse.wb_warehouse_id,
        "warehouse_name": warehouse.name,
        "wb_amount": wb_amount,
        "verified_stock_match": True,
      }
    elif intake_quantity <= 0:
      raise IntakeError("Количество должно быть больше 0")

  product = (
    Product.objects.select_for_update()
    .filter(seller=seller, barcode=barcode, marketplace=mp)
    .select_related("cell", "seller")
    .first()
  )

  if stock_mode == STOCK_MODE_SYNC_FROM_WB:
    if product:
      product.quantity = intake_quantity
      product.save(update_fields=["quantity", "updated_at"])
      is_new = False
    else:
      cell = _assign_cell(
        seller,
        cell_mode,
        cell_id,
        mp,
        sequential=sync_variant == "scan",
      )
      marking = lookup_marking_for_barcode(seller, barcode)
      product = Product.objects.create(
        seller=seller,
        barcode=barcode,
        name=name.strip() or marking.title,
        cell=cell,
        quantity=intake_quantity,
        marketplace=mp,
        requires_marking=marking.requires_marking if marking.wb_found else False,
      )
      refresh_cell_occupied(cell)
      is_new = True
  elif product:
    product.quantity += intake_quantity
    product.save(update_fields=["quantity", "updated_at"])
    is_new = False
  else:
    cell = _assign_cell(seller, cell_mode, cell_id, mp)
    marking = lookup_marking_for_barcode(seller, barcode) if mp == WB else None
    product = Product.objects.create(
      seller=seller,
      barcode=barcode,
      name=name.strip() or (marking.title if marking else ""),
      cell=cell,
      quantity=intake_quantity,
      marketplace=mp,
      requires_marking=(marking.requires_marking if marking and marking.wb_found else False),
    )
    refresh_cell_occupied(cell)
    is_new = True

  if mp == OZON:
    comment = f"Приёмка Ozon +{intake_quantity} шт."
  elif stock_mode == STOCK_MODE_SYNC_FROM_WB:
    comment = (
      f"Сверка с WB, склад {warehouse.name or warehouse.wb_warehouse_id}: "
      f"остаток CRM = {intake_quantity} шт. (подтверждено менеджером)"
    )
  else:
    comment = f"Приёмка +{intake_quantity} шт., склад WB {warehouse.name or warehouse.wb_warehouse_id}"

  StockOperation.objects.create(
    product=product,
    operation_type=StockOperation.OperationType.INTAKE
    if stock_mode == STOCK_MODE_INTAKE
    else StockOperation.OperationType.ADJUSTMENT,
    quantity=intake_quantity if stock_mode == STOCK_MODE_INTAKE else intake_quantity,
    performed_by=user,
    comment=comment,
  )

  if stock_mode == STOCK_MODE_INTAKE and mp != OZON and warehouse is not None:
    try:
      wb_sync = push_wb_stock_increment(seller, warehouse, barcode, intake_quantity)
    except WBStockError as exc:
      raise IntakeError(str(exc)) from exc

  warehouse_label = ""
  if warehouse is not None:
    warehouse_label = warehouse.name or str(warehouse.wb_warehouse_id)

  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.INTAKE,
    message=(
      f"Приёмка {intake_quantity} шт., баркод {barcode}"
      + (f", склад WB {warehouse_label}" if warehouse_label else f", {mp}")
    ),
    details={
      "barcode": barcode,
      "quantity": intake_quantity,
      "cell": product.cell.number,
      "is_new_product": is_new,
      "requires_marking": product.requires_marking,
      "stock_mode": stock_mode,
      "marketplace": mp,
      "wb_warehouse_id": warehouse.wb_warehouse_id if warehouse else None,
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
