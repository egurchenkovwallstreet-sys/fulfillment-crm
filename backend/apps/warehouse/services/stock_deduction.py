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


def deduct_stock_for_delivery(
  *,
  order: Order,
  supply: Supply,
  user=None,
) -> dict:
  """Списать 1 шт. с остатка ячейки. Идемпотентно по флагу supply.stock_deducted."""
  if supply.stock_deducted:
    product = resolve_order_product(order)
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
    comment=(
      f"Списание: поставка WB {supply.wb_supply_id}, заказ #{order.wb_order_id}"
    ),
  )

  supply.stock_deducted = True
  supply.save(update_fields=["stock_deducted", "updated_at"])

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
