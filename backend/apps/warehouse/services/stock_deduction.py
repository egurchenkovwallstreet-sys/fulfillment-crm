"""Списание остатков при передаче заказа в доставку (ТЗ §10)."""
from __future__ import annotations

from apps.integrations.models import AuditLog
from apps.orders.models import Order, Supply
from apps.warehouse.models import Product, StockOperation
from apps.warehouse.services.cells import refresh_cell_occupied


class StockDeductionError(Exception):
  pass


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
    order_stock_already_deducted(order, supply) for order in orders
  )
  if supply.stock_deducted != all_deducted:
    supply.stock_deducted = all_deducted
    supply.save(update_fields=["stock_deducted", "updated_at"])


def deduct_stock_for_delivery(
  *,
  order: Order,
  supply: Supply,
  user=None,
) -> dict:
  """Списать 1 шт. с остатка ячейки. Идемпотентно по складской операции заказа."""
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
  Списать остатки по заказам «в доставке» (complete+waiting), если поставка уже в CRM,
  но списание ещё не прошло (например, заказ ушёл в доставку из ЛК WB).
  """
  from apps.orders.services.wb_status import wb_in_delivery_q
  from apps.sellers.services.warehouse_filter import filter_orders_for_seller

  orders = list(
    filter_orders_for_seller(
      Order.objects.filter(seller=seller, assembly_hidden=False).filter(wb_in_delivery_q()),
      seller,
    ).prefetch_related("supplies")
  )

  deducted = 0
  already = 0
  no_supply = 0
  errors: list[dict] = []

  for order in orders:
    supply = (
      order.supplies.filter(status=Supply.Status.CONFIRMED)
      .exclude(wb_supply_id="")
      .order_by("-created_at")
      .first()
    )
    if not supply:
      supply = (
        order.supplies.exclude(wb_supply_id="")
        .order_by("-created_at")
        .first()
      )
    if not supply:
      no_supply += 1
      continue
    try:
      result = deduct_stock_for_delivery(order=order, supply=supply, user=user)
      if result["deducted"]:
        deducted += 1
      elif result["already_deducted"]:
        already += 1
    except StockDeductionError as exc:
      errors.append({
        "order_id": order.id,
        "wb_order_id": order.wb_order_id,
        "error": str(exc),
      })

  return {
    "deducted": deducted,
    "already_deducted": already,
    "no_supply": no_supply,
    "errors": errors,
  }


def deduct_stock_for_confirmed_supply(
  supply: Supply,
  *,
  user=None,
) -> dict:
  """Списать остатки по всем заказам поставки после подтверждения WB (ТЗ §10)."""
  deducted = 0
  already = 0
  errors: list[dict] = []

  for order in supply.orders.select_related("product", "seller", "product__cell"):
    try:
      result = deduct_stock_for_delivery(order=order, supply=supply, user=user)
      if result["deducted"]:
        deducted += 1
      elif result["already_deducted"]:
        already += 1
    except StockDeductionError as exc:
      errors.append({
        "order_id": order.id,
        "wb_order_id": order.wb_order_id,
        "error": str(exc),
      })

  return {"deducted": deducted, "already_deducted": already, "errors": errors}
