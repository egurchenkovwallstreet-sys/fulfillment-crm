"""Списание остатков при печати FBS-стикера и передаче в доставку (ТЗ §10)."""
from __future__ import annotations

from apps.integrations.models import AuditLog
from apps.orders.models import Order, PickList, Supply
from apps.orders.services.marking_verification import order_marking_ready
from apps.orders.services.order_sticker import order_sticker_printed_in_crm
from apps.warehouse.models import Product, StockOperation
from apps.warehouse.services.cells import refresh_cell_occupied
from apps.warehouse.services.marking_lookup import resolve_product_requires_marking


class StockDeductionError(Exception):
  pass


def normalize_sticker_key(part_a: str, part_b: str) -> str:
  a = (part_a or "").strip()
  b = (part_b or "").strip()
  if a and b:
    return f"{a}|{b}"
  return a or b


def order_on_active_pick_list(order: Order) -> bool:
  if not order.pick_list_id:
    return False
  pick_list = order.pick_list
  if pick_list is None:
    pick_list = PickList.objects.filter(pk=order.pick_list_id).first()
  return pick_list is not None and not pick_list.is_completed


def assert_order_ready_for_crm_stock_deduction(order: Order) -> None:
  """Списание через CRM только после листа подбора, стикера и ЧЗ (если нужен)."""
  if not order_on_active_pick_list(order):
    raise StockDeductionError(
      "Заказ не в активном листе подбора — списание только после сборки в CRM",
    )
  if not order_sticker_printed_in_crm(order):
    raise StockDeductionError(
      "Стикер FBS не распечатан через CRM — сначала завершите сборку",
    )
  if resolve_product_requires_marking(order.product, order.barcode, order.seller):
    if not order_marking_ready(order):
      raise StockDeductionError(
        "Честный знак не привязан или не подтверждён WB — списание невозможно",
      )


def order_has_crm_shipment_deduction(order: Order) -> bool:
  """Любое списание по заказу (стикер FBS или legacy «в доставку»)."""
  needle = f"заказ #{order.wb_order_id}"
  return StockOperation.objects.filter(
    operation_type=StockOperation.OperationType.SHIPMENT,
    comment__contains=needle,
  ).exists()


def _sticker_shipment_comment(order: Order) -> str:
  sticker_key = normalize_sticker_key(order.sticker_part_a, order.sticker_part_b)
  sticker_label = sticker_key or "—"
  return (
    f"Списание: стикер FBS {sticker_label}, баркод {order.barcode}, "
    f"заказ #{order.wb_order_id}"
  )


def sticker_stock_already_deducted(order: Order) -> bool:
  """Идемпотентность: один стикер (partA|partB) — одно списание."""
  sticker_key = normalize_sticker_key(order.sticker_part_a, order.sticker_part_b)
  if sticker_key:
    return StockOperation.objects.filter(
      operation_type=StockOperation.OperationType.SHIPMENT,
      comment__contains=f"стикер FBS {sticker_key}",
    ).exists()
  return order_has_crm_shipment_deduction(order)


def deduct_stock_for_sticker_print(*, order: Order, user=None) -> dict:
  """
  Списать 1 шт. при первой печати FBS-стикера в CRM.
  Повторная печать того же стикера (reprint) не вызывает эту функцию.
  """
  if not order_on_active_pick_list(order):
    raise StockDeductionError(
      "Заказ не в активном листе подбора — списание только после сборки в CRM",
    )

  if sticker_stock_already_deducted(order):
    product = resolve_order_product(order)
    return {
      "deducted": False,
      "already_deducted": True,
      "quantity": product.quantity if product else 0,
      "cell_number": product.cell.number if product and product.cell_id else "",
      "barcode": product.barcode if product else order.barcode,
    }

  product = check_stock_for_delivery(order)

  product.quantity -= 1
  product.save(update_fields=["quantity", "updated_at"])
  refresh_cell_occupied(product.cell)

  if not order.product_id:
    order.product = product
    order.save(update_fields=["product", "updated_at"])

  comment = _sticker_shipment_comment(order)
  StockOperation.objects.create(
    product=product,
    operation_type=StockOperation.OperationType.SHIPMENT,
    quantity=1,
    performed_by=user,
    comment=comment,
  )

  AuditLog.objects.create(
    user=user,
    seller=order.seller,
    action_type=AuditLog.ActionType.LABEL_PRINT,
    message=(
      f"Списание при печати стикера: 1 шт., баркод {product.barcode}, "
      f"заказ WB #{order.wb_order_id}, ячейка №{product.cell.number}, "
      f"остаток {product.quantity} шт."
    ),
    details={
      "order_id": order.id,
      "wb_order_id": order.wb_order_id,
      "product_id": product.id,
      "cell": product.cell.number,
      "quantity_after": product.quantity,
      "sticker_key": normalize_sticker_key(order.sticker_part_a, order.sticker_part_b),
    },
  )

  return {
    "deducted": True,
    "already_deducted": False,
    "quantity": product.quantity,
    "cell_number": product.cell.number,
    "barcode": product.barcode,
  }


def stock_deduction_info(order: Order) -> dict:
  """Только чтение: был ли списан остаток при печати стикера."""
  product = resolve_order_product(order)
  already = order_has_crm_shipment_deduction(order)
  return {
    "deducted": False,
    "already_deducted": already,
    "quantity": product.quantity if product else 0,
    "cell_number": product.cell.number if product and product.cell_id else "",
    "barcode": product.barcode if product else order.barcode,
  }


def assert_order_stock_deducted_at_print(order: Order) -> None:
  """
  Перед «в доставку»: стикер напечатан, остаток списан при печати.
  Заказы уже «в доставке» остаток не трогаем (актуальные остатки — из WB).
  """
  if order.status == Order.Status.IN_DELIVERY:
    return
  if not order_sticker_printed_in_crm(order):
    raise StockDeductionError(
      "Стикер FBS не распечатан через CRM — сначала завершите сборку",
    )
  if not order_has_crm_shipment_deduction(order):
    raise StockDeductionError(
      "Остаток не списан при печати стикера — распечатайте стикер FBS через сборку",
    )


def resolve_order_product(order: Order) -> Product | None:
  if order.product_id:
    return Product.objects.select_related("cell").filter(pk=order.product_id).first()
  return (
    Product.objects.filter(seller=order.seller, barcode=order.barcode)
    .select_related("cell")
    .first()
  )


def check_stock_for_delivery(order: Order) -> Product:
  product = resolve_order_product(order)
  if not product:
    raise StockDeductionError(
      f"Товар {order.barcode} не принят на склад CRM — сначала выполните приёмку",
    )
  if product.quantity < 1:
    raise StockDeductionError(
      f"Недостаточно остатка: баркод {order.barcode}, "
      f"ячейка №{product.cell.number}, остаток {product.quantity} шт.",
    )
  return product


def _shipment_comment(supply: Supply, order: Order) -> str:
  return (
    f"Списание: поставка WB {supply.wb_supply_id}, заказ #{order.wb_order_id}"
  )


def order_stock_already_deducted(order: Order, supply: Supply) -> bool:
  """Идемпотентность по заказу внутри поставки (поставка может содержать несколько заказов)."""
  return StockOperation.objects.filter(
    operation_type=StockOperation.OperationType.SHIPMENT,
    comment=_shipment_comment(supply, order),
  ).exists()


def _refresh_supply_stock_flag(supply: Supply) -> None:
  orders = list(supply.orders.all())
  if not orders:
    return
  all_deducted = all(
    order_has_crm_shipment_deduction(order) for order in orders
  )
  if supply.stock_deducted != all_deducted:
    supply.stock_deducted = all_deducted
    supply.save(update_fields=["stock_deducted", "updated_at"])


def deduct_stock_for_delivery(
  *,
  order: Order,
  supply: Supply,
  user=None,
  require_crm_checks: bool = False,
) -> dict:
  """Списать 1 шт. с остатка ячейки. Идемпотентно по складской операции заказа."""
  if require_crm_checks:
    assert_order_ready_for_crm_stock_deduction(order)

  if order_stock_already_deducted(order, supply):
    product = resolve_order_product(order)
    _refresh_supply_stock_flag(supply)
    return {
      "deducted": False,
      "already_deducted": True,
      "quantity": product.quantity if product else 0,
      "cell_number": product.cell.number if product else "",
      "barcode": product.barcode if product else order.barcode,
    }

  product = check_stock_for_delivery(order)

  product.quantity -= 1
  product.save(update_fields=["quantity", "updated_at"])
  refresh_cell_occupied(product.cell)

  if not order.product_id:
    order.product = product
    order.save(update_fields=["product", "updated_at"])

  StockOperation.objects.create(
    product=product,
    operation_type=StockOperation.OperationType.SHIPMENT,
    quantity=1,
    performed_by=user,
    comment=_shipment_comment(supply, order),
  )

  _refresh_supply_stock_flag(supply)

  AuditLog.objects.create(
    user=user,
    seller=order.seller,
    action_type=AuditLog.ActionType.SUPPLY,
    message=(
      f"Списание 1 шт., баркод {product.barcode}, "
      f"ячейка №{product.cell.number}, остаток {product.quantity} шт."
    ),
    details={
      "order_id": order.id,
      "wb_order_id": order.wb_order_id,
      "wb_supply_id": supply.wb_supply_id,
      "product_id": product.id,
      "cell": product.cell.number,
      "quantity_after": product.quantity,
    },
  )

  return {
    "deducted": True,
    "already_deducted": False,
    "quantity": product.quantity,
    "cell_number": product.cell.number,
    "barcode": product.barcode,
  }


def deduct_pending_delivery_stock(seller, *, user=None) -> dict:
  """
  Отключено: заказы «в доставке» не списывают CRM-остаток.
  Актуальные остатки подтягиваются из ЛК WB селлера.
  """
  return {
    "deducted": 0,
    "already_deducted": 0,
    "no_supply": 0,
    "errors": [],
    "skipped_in_delivery": True,
  }


def deduct_stock_for_confirmed_supply(
  supply: Supply,
  *,
  user=None,
) -> dict:
  """Списание только при печати FBS-стикера; поставка в доставке — без досписания."""
  already = 0
  for order in supply.orders.all():
    if order_has_crm_shipment_deduction(order):
      already += 1
  return {"deducted": 0, "already_deducted": already, "errors": []}


def _off_crm_shipment_comment(*, wb_order_id: int, sticker_number: str) -> str:
  sticker = (sticker_number or "").strip() or "—"
  return f"Списание: отгрузка вне CRM, стикер {sticker}, заказ #{wb_order_id}"


def off_crm_shipment_already_deducted(*, wb_order_id: int, sticker_number: str) -> bool:
  return StockOperation.objects.filter(
    operation_type=StockOperation.OperationType.SHIPMENT,
    comment=_off_crm_shipment_comment(wb_order_id=wb_order_id, sticker_number=sticker_number),
  ).exists()


def deduct_stock_for_off_crm_shipment(
  *,
  seller,
  barcode: str,
  wb_order_id: int,
  sticker_number: str,
  user=None,
) -> dict:
  """Ручное списание по решению менеджера для отгрузки через ЛК WB."""
  if off_crm_shipment_already_deducted(
    wb_order_id=wb_order_id,
    sticker_number=sticker_number,
  ):
    product = Product.objects.filter(seller=seller, barcode=barcode).first()
    return {
      "deducted": False,
      "already_deducted": True,
      "quantity": product.quantity if product else 0,
      "cell_number": product.cell.number if product and product.cell_id else "",
      "barcode": barcode,
    }

  product = Product.objects.filter(seller=seller, barcode=barcode).select_related("cell").first()
  if not product:
    raise StockDeductionError(
      f"Товар {barcode} не принят на склад CRM — сначала выполните приёмку",
    )
  if product.quantity < 1:
    raise StockDeductionError(
      f"Недостаточно остатка: баркод {barcode}, "
      f"ячейка №{product.cell.number}, остаток {product.quantity} шт.",
    )

  product.quantity -= 1
  product.save(update_fields=["quantity", "updated_at"])
  refresh_cell_occupied(product.cell)

  comment = _off_crm_shipment_comment(
    wb_order_id=wb_order_id,
    sticker_number=sticker_number,
  )
  StockOperation.objects.create(
    product=product,
    operation_type=StockOperation.OperationType.SHIPMENT,
    quantity=1,
    performed_by=user,
    comment=comment,
  )

  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.SUPPLY,
    message=(
      f"Списание вне CRM: 1 шт., баркод {product.barcode}, "
      f"заказ WB #{wb_order_id}, стикер {sticker_number or '—'}"
    ),
    details={
      "wb_order_id": wb_order_id,
      "barcode": barcode,
      "product_id": product.id,
      "cell": product.cell.number,
      "quantity_after": product.quantity,
      "off_crm": True,
    },
  )

  return {
    "deducted": True,
    "already_deducted": False,
    "quantity": product.quantity,
    "cell_number": product.cell.number,
    "barcode": product.barcode,
  }
