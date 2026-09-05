from dataclasses import dataclass

from django.db import transaction

from apps.integrations.models import AuditLog
from apps.integrations.marketplace import OZON, WB, normalize_marketplace
from apps.sellers.models import Seller

from apps.warehouse.models import Cell, Product, ProductWarehouseStock, StockOperation
from apps.warehouse.services.cell_label import build_cell_label_data
from apps.warehouse.services.cells import create_cell_with_next_number, first_free_cell, refresh_cell_occupied
from apps.warehouse.services.liter_pricing import apply_product_dimensions
from apps.warehouse.services.marking_lookup import lookup_marking_for_barcode
from apps.warehouse.services.stock_balance import (
  compute_wb_amount_from_crm,
  count_reserved_new_orders,
)
from apps.warehouse.services.wb_stocks import (
  STOCK_MODE_INTAKE,
  STOCK_MODE_SET_ACTUAL,
  STOCK_MODE_SYNC_FROM_WB,
  WBStockError,
  fetch_wb_stock_for_barcode,
  get_seller_warehouse,
  push_wb_stock_absolute,
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
  crm_quantity_before: int = 0
  crm_quantity_after: int = 0
  wb_quantity_before: int | None = None
  wb_quantity_target: int = 0
  wb_quantity_actual: int | None = None
  reserved_new_orders: int = 0
  intake_quantity: int = 0
  physical_quantity: int | None = None
  restock_required: bool = False
  verified: bool = True
  warehouse_name: str = ""


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


def _write_wb_balance_for_intake(
  *,
  seller: Seller,
  product: Product,
  warehouse,
  barcode: str,
  crm_quantity: int,
  reserved_new_orders: int,
) -> tuple[dict, bool, int, bool, int, int]:
  wb_target, restock_required = compute_wb_amount_from_crm(crm_quantity, reserved_new_orders)
  wb_before = fetch_wb_stock_for_barcode(seller, warehouse, barcode)
  push_result = push_wb_stock_absolute(seller, warehouse, barcode, wb_target)
  ProductWarehouseStock.objects.update_or_create(
    product=product,
    seller_warehouse=warehouse,
    defaults={"quantity": wb_target},
  )
  wb_actual = fetch_wb_stock_for_barcode(seller, warehouse, barcode)
  verified = wb_actual == wb_target
  wb_sync = {
    **push_result,
    "target_wb_amount": wb_target,
    "actual_wb_amount": wb_actual,
    "verified": verified,
    "reserved_new_orders": reserved_new_orders,
    "crm_quantity": crm_quantity,
  }
  return wb_sync, verified, wb_target, restock_required, wb_before, wb_actual


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
  length_cm=None,
  width_cm=None,
  height_cm=None,
) -> IntakeResult:
  mp = normalize_marketplace(marketplace)
  barcode = barcode.strip()
  if not barcode:
    raise IntakeError("Баркод не может быть пустым")

  warehouse = None
  wb_sync: dict | None = None
  intake_quantity = quantity
  reserved_new_orders = 0
  restock_required = False
  verified = True
  wb_quantity_before: int | None = None
  wb_quantity_target = 0
  wb_quantity_actual: int | None = None
  physical_quantity: int | None = None

  if mp == OZON:
    if stock_mode in (STOCK_MODE_SYNC_FROM_WB, STOCK_MODE_SET_ACTUAL):
      raise IntakeError("Режим недоступен на вкладке Ozon")
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
    elif stock_mode == STOCK_MODE_SET_ACTUAL:
      if intake_quantity < 0:
        raise IntakeError("Количество не может быть отрицательным")
      physical_quantity = intake_quantity
    elif intake_quantity <= 0:
      raise IntakeError("Количество должно быть больше 0")

  product = (
    Product.objects.select_for_update()
    .filter(seller=seller, barcode=barcode, marketplace=mp)
    .select_related("cell", "seller")
    .first()
  )
  crm_quantity_before = product.quantity if product else 0

  if stock_mode in (STOCK_MODE_SYNC_FROM_WB, STOCK_MODE_SET_ACTUAL):
    if stock_mode == STOCK_MODE_SET_ACTUAL:
      crm_quantity_after = intake_quantity
    else:
      crm_quantity_after = intake_quantity

    if product:
      product.quantity = crm_quantity_after
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
        quantity=crm_quantity_after,
        marketplace=mp,
        requires_marking=marking.requires_marking if marking.wb_found else False,
      )
      refresh_cell_occupied(cell)
      is_new = True
  elif product:
    crm_quantity_after = crm_quantity_before + intake_quantity
    product.quantity = crm_quantity_after
    product.save(update_fields=["quantity", "updated_at"])
    is_new = False
  else:
    crm_quantity_after = intake_quantity
    cell = _assign_cell(seller, cell_mode, cell_id, mp)
    marking = lookup_marking_for_barcode(seller, barcode) if mp == WB else None
    product = Product.objects.create(
      seller=seller,
      barcode=barcode,
      name=name.strip() or (marking.title if marking else ""),
      cell=cell,
      quantity=crm_quantity_after,
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
      f"остаток CRM = {crm_quantity_after} шт. (подтверждено менеджером)"
    )
  elif stock_mode == STOCK_MODE_SET_ACTUAL:
    comment = (
      f"Фактический остаток при приёмке: CRM {crm_quantity_after} шт., "
      f"склад {warehouse.name or warehouse.wb_warehouse_id}"
    )
  else:
    comment = (
      f"Приёмка +{intake_quantity} шт., CRM {crm_quantity_before}→{crm_quantity_after}, "
      f"склад WB {warehouse.name or warehouse.wb_warehouse_id}"
    )

  StockOperation.objects.create(
    product=product,
    operation_type=StockOperation.OperationType.INTAKE
    if stock_mode == STOCK_MODE_INTAKE
    else StockOperation.OperationType.ADJUSTMENT,
    quantity=intake_quantity if stock_mode == STOCK_MODE_INTAKE else crm_quantity_after,
    performed_by=user,
    comment=comment,
  )

  if stock_mode in (STOCK_MODE_INTAKE, STOCK_MODE_SET_ACTUAL) and mp != OZON and warehouse is not None:
    reserved_new_orders = count_reserved_new_orders(seller, barcode, marketplace=mp)
    try:
      wb_sync, verified, wb_quantity_target, restock_required, wb_quantity_before, wb_quantity_actual = (
        _write_wb_balance_for_intake(
          seller=seller,
          product=product,
          warehouse=warehouse,
          barcode=barcode,
          crm_quantity=crm_quantity_after,
          reserved_new_orders=reserved_new_orders,
        )
      )
      wb_sync["mode"] = stock_mode
    except WBStockError as exc:
      raise IntakeError(str(exc)) from exc

  if any(value is not None for value in (length_cm, width_cm, height_cm)):
    apply_product_dimensions(
      product,
      length_cm=length_cm,
      width_cm=width_cm,
      height_cm=height_cm,
    )

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
      + (f", {'сверка OK' if verified else 'расхождение WB'}" if stock_mode in (STOCK_MODE_INTAKE, STOCK_MODE_SET_ACTUAL) and mp != OZON else "")
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
      "crm_quantity_before": crm_quantity_before,
      "crm_quantity_after": crm_quantity_after,
      "wb_quantity_target": wb_quantity_target,
      "reserved_new_orders": reserved_new_orders,
      "verified": verified,
      "restock_required": restock_required,
    },
  )

  cell_label = build_cell_label_data(product) if is_new else None
  return IntakeResult(
    product=product,
    print_cell_label=is_new,
    cell_label=cell_label,
    stock_mode=stock_mode,
    wb_sync=wb_sync,
    crm_quantity_before=crm_quantity_before,
    crm_quantity_after=crm_quantity_after,
    wb_quantity_before=wb_quantity_before,
    wb_quantity_target=wb_quantity_target,
    wb_quantity_actual=wb_quantity_actual,
    reserved_new_orders=reserved_new_orders,
    intake_quantity=intake_quantity,
    physical_quantity=physical_quantity,
    restock_required=restock_required,
    verified=verified,
    warehouse_name=warehouse_label,
  )


@transaction.atomic
def force_rewrite_intake(
  *,
  seller: Seller,
  barcode: str,
  crm_quantity: int,
  wb_warehouse_id: int,
  stock_mode: str,
  user,
  marketplace: str = WB,
) -> IntakeResult:
  """Повторная запись CRM и WB после расхождения сверки."""
  mp = normalize_marketplace(marketplace)
  barcode = barcode.strip()
  if not barcode:
    raise IntakeError("Баркод не может быть пустым")
  if crm_quantity < 0:
    raise IntakeError("Количество CRM не может быть отрицательным")

  try:
    warehouse = get_seller_warehouse(seller, wb_warehouse_id)
  except WBStockError as exc:
    raise IntakeError(str(exc)) from exc

  product = (
    Product.objects.select_for_update()
    .filter(seller=seller, barcode=barcode, marketplace=mp)
    .select_related("cell", "seller")
    .first()
  )
  if not product:
    raise IntakeError("Товар не найден — сначала выполните приёмку")

  crm_quantity_before = product.quantity
  product.quantity = crm_quantity
  product.save(update_fields=["quantity", "updated_at"])

  reserved_new_orders = count_reserved_new_orders(seller, barcode, marketplace=mp)
  wb_sync, verified, wb_quantity_target, restock_required, wb_quantity_before, wb_quantity_actual = (
    _write_wb_balance_for_intake(
      seller=seller,
      product=product,
      warehouse=warehouse,
      barcode=barcode,
      crm_quantity=crm_quantity,
      reserved_new_orders=reserved_new_orders,
    )
  )
  wb_sync["mode"] = stock_mode

  StockOperation.objects.create(
    product=product,
    operation_type=StockOperation.OperationType.ADJUSTMENT,
    quantity=crm_quantity,
    performed_by=user,
    comment=(
      f"Приёмка (повтор): CRM {crm_quantity}, WB {wb_quantity_target}, "
      f"склад {warehouse.name or warehouse.wb_warehouse_id}"
    ),
  )

  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.INTAKE,
    message=(
      f"Приёмка (повтор) баркод {barcode}: CRM→{crm_quantity}, WB→{wb_quantity_target}, "
      f"{'сверка OK' if verified else 'расхождение WB'}"
    ),
    details={
      "barcode": barcode,
      "crm_quantity": crm_quantity,
      "wb_quantity_target": wb_quantity_target,
      "verified": verified,
      "retry": True,
      "stock_mode": stock_mode,
    },
  )

  warehouse_label = warehouse.name or str(warehouse.wb_warehouse_id)
  return IntakeResult(
    product=product,
    print_cell_label=False,
    cell_label=None,
    stock_mode=stock_mode,
    wb_sync=wb_sync,
    crm_quantity_before=crm_quantity_before,
    crm_quantity_after=crm_quantity,
    wb_quantity_before=wb_quantity_before,
    wb_quantity_target=wb_quantity_target,
    wb_quantity_actual=wb_quantity_actual,
    reserved_new_orders=reserved_new_orders,
    intake_quantity=0,
    physical_quantity=crm_quantity if stock_mode == STOCK_MODE_SET_ACTUAL else None,
    restock_required=restock_required,
    verified=verified,
    warehouse_name=warehouse_label,
  )
