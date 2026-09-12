"""Учёт CRM-остатков по дням для начисления хранения."""
from __future__ import annotations

import re
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from apps.sellers.services.calendar_periods import today_local
from apps.warehouse.models import Product, ProductDailyQuantity, StockOperation

CRM_AFTER_RE = re.compile(r"→ CRM (\d+)", re.IGNORECASE)
STOCK_AFTER_RE = re.compile(r"остаток \d+ → (\d+)", re.IGNORECASE)
ARTICLE_AFTER_RE = re.compile(r"→ (\d+)")


def operation_local_date(operation: StockOperation) -> date:
  return timezone.localtime(operation.created_at).date()


def apply_stock_operation_balance(balance: int, operation: StockOperation) -> int:
  """Восстановить CRM-остаток после складской операции (best effort)."""
  balance = max(0, int(balance))
  qty = int(operation.quantity or 0)
  op_type = operation.operation_type
  comment = operation.comment or ""

  if op_type == StockOperation.OperationType.INTAKE:
    return balance + qty

  if op_type == StockOperation.OperationType.SHIPMENT:
    return max(0, balance - abs(qty))

  if op_type == StockOperation.OperationType.RETURN:
    return balance + abs(qty)

  match = CRM_AFTER_RE.search(comment)
  if match:
    return int(match.group(1))

  match = STOCK_AFTER_RE.search(comment)
  if match:
    return int(match.group(1))

  if "Приёмка по артикулам" in comment and "→" in comment:
    match = ARTICLE_AFTER_RE.search(comment)
    if match:
      return int(match.group(1))

  if any(
    marker in comment
    for marker in (
      "Инвентаризация",
      "Сверка с WB",
      "Приёмка (повтор)",
      "Фактический остаток",
    )
  ):
    return max(0, qty)

  if qty == 0:
    return balance

  return max(0, balance + qty)


def record_product_daily_quantity(
  product: Product,
  *,
  quantity: int | None = None,
  on_date: date | None = None,
) -> ProductDailyQuantity:
  on_date = on_date or today_local()
  qty = max(0, int(product.quantity if quantity is None else quantity))
  row, _ = ProductDailyQuantity.objects.update_or_create(
    product=product,
    date=on_date,
    defaults={"quantity": qty},
  )
  return row


def touch_positive_stock_since(
  product: Product,
  previous_qty: int,
  new_qty: int,
  *,
  on_date: date | None = None,
) -> None:
  on_date = on_date or today_local()
  previous_qty = max(0, int(previous_qty))
  new_qty = max(0, int(new_qty))
  update_fields: list[str] = []

  if previous_qty <= 0 and new_qty > 0:
    product.positive_stock_since = on_date
    update_fields.append("positive_stock_since")
  elif previous_qty > 0 and new_qty <= 0:
    product.positive_stock_since = None
    update_fields.append("positive_stock_since")

  if update_fields:
    Product.objects.filter(pk=product.pk).update(
      positive_stock_since=product.positive_stock_since,
      updated_at=timezone.now(),
    )


def rebuild_product_daily_quantities(product: Product) -> int:
  """Восстановить снимки остатков из StockOperation (для миграции и догонки)."""
  operations = list(
    StockOperation.objects.filter(product=product).order_by("created_at", "id")
  )
  if not operations:
    if product.quantity > 0:
      record_product_daily_quantity(product, quantity=product.quantity, on_date=today_local())
      product.positive_stock_since = today_local()
      product.save(update_fields=["positive_stock_since", "updated_at"])
      return 1
    return 0

  balance = 0
  snapshots: dict[date, int] = {}
  for operation in operations:
    balance = apply_stock_operation_balance(balance, operation)
    snapshots[operation_local_date(operation)] = balance

  if product.quantity != balance:
    snapshots[today_local()] = int(product.quantity or 0)
    balance = int(product.quantity or 0)

  saved = 0
  for snap_date, qty in snapshots.items():
    ProductDailyQuantity.objects.update_or_create(
      product=product,
      date=snap_date,
      defaults={"quantity": max(0, qty)},
    )
    saved += 1

  product.positive_stock_since = compute_current_positive_stock_since(product)
  product.save(update_fields=["positive_stock_since", "updated_at"])
  return saved


def first_snapshot_date(product: Product) -> date | None:
  return (
    ProductDailyQuantity.objects.filter(product=product)
    .order_by("date")
    .values_list("date", flat=True)
    .first()
  )


def quantity_on_date(product: Product, target_date: date) -> int:
  exact = (
    ProductDailyQuantity.objects.filter(product=product, date=target_date)
    .values_list("quantity", flat=True)
    .first()
  )
  if exact is not None:
    return int(exact)

  first_date = first_snapshot_date(product)
  if first_date is None or target_date < first_date:
    return 0

  previous = (
    ProductDailyQuantity.objects.filter(product=product, date__lt=target_date)
    .order_by("-date")
    .values_list("quantity", flat=True)
    .first()
  )
  return int(previous or 0)


def compute_current_positive_stock_since(product: Product, *, to_date: date | None = None) -> date | None:
  """Первый день текущего непрерывного периода с quantity > 0."""
  if product.quantity <= 0:
    return None

  first_date = first_snapshot_date(product)
  if first_date is None:
    return product.positive_stock_since or today_local()

  to_date = to_date or today_local()
  since: date | None = None
  previous_qty = 0
  current = first_date
  while current <= to_date:
    qty = quantity_on_date(product, current)
    if previous_qty <= 0 and qty > 0:
      since = current
    elif qty <= 0:
      since = None
    previous_qty = qty
    current += timedelta(days=1)
  return since or product.positive_stock_since


def first_positive_quantity_date(product: Product) -> date | None:
  """Первый день в истории снимков, когда CRM-остаток был > 0."""
  first_date = first_snapshot_date(product)
  if first_date is None:
    if product.quantity > 0:
      return product.positive_stock_since or today_local()
    return None

  to_date = today_local()
  current = first_date
  while current <= to_date:
    if quantity_on_date(product, current) > 0:
      return current
    current += timedelta(days=1)
  return None


def iter_positive_quantity_days(
  product: Product,
  from_date: date,
  to_date: date,
) -> list[tuple[date, int]]:
  days: list[tuple[date, int]] = []
  current = from_date
  while current <= to_date:
    qty = quantity_on_date(product, current)
    if qty > 0:
      days.append((current, qty))
    current += timedelta(days=1)
  return days


@transaction.atomic
def rebuild_all_product_daily_quantities() -> dict:
  updated_products = 0
  snapshots = 0
  for product in Product.objects.all().iterator():
    count = rebuild_product_daily_quantities(product)
    if count:
      updated_products += 1
      snapshots += count
  return {"products": updated_products, "snapshots": snapshots}
