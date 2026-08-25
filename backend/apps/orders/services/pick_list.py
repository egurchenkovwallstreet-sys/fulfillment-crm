from collections import defaultdict

from django.db import transaction

from apps.orders.models import Order, PickList, PickListItem
from apps.orders.services.wb_status import WB_SUPPLIER_NEW
from apps.sellers.models import Seller
from apps.warehouse.models import Cell, Product


class PickListError(Exception):
  pass


@transaction.atomic
def generate_pick_list(seller: Seller, *, user=None) -> PickList:
  existing = (
    PickList.objects.filter(seller=seller, is_completed=False)
    .prefetch_related("items__cell", "items__product")
    .first()
  )
  if existing and existing.items.exists():
    return existing

  from apps.orders.services.supply_flow import new_stage_orders_queryset

  orders = list(
    new_stage_orders_queryset(seller)
    .filter(pick_list__isnull=True)
    .select_related("product", "product__cell")
  )

  if not orders:
    raise PickListError("Нет новых заказов для формирования листа подбора")

  pick_list = PickList.objects.create(seller=seller)

  # Группировка по ячейке + баркод (TZ п. 6.2)
  grouped: dict[tuple[int, int, str], dict] = defaultdict(
    lambda: {"quantity": 0, "order_ids": []}
  )
  missing_product: list[int] = []

  for order in orders:
    product = order.product
    if not product:
      product = Product.objects.filter(
        seller=seller,
        barcode=order.barcode,
      ).select_related("cell").first()
      if product:
        order.product = product
        order.save(update_fields=["product", "updated_at"])

    if not product:
      missing_product.append(order.wb_order_id)
      continue

    key = (product.cell_id, product.id, order.barcode)
    grouped[key]["quantity"] += 1
    grouped[key]["order_ids"].append(order.id)
    grouped[key]["product"] = product
    grouped[key]["cell"] = product.cell

  if not grouped:
    pick_list.delete()
    raise PickListError(
      "Ни один заказ не привязан к товару на складе. "
      f"Без товара: {len(missing_product)} зак."
    )

  items: list[PickListItem] = []
  for (_cell_id, _product_id, barcode), data in sorted(
    grouped.items(),
    key=lambda entry: int(entry[1]["cell"].number),
  ):
    items.append(
      PickListItem(
        pick_list=pick_list,
        cell=data["cell"],
        product=data["product"],
        barcode=barcode,
        quantity=data["quantity"],
      )
    )

  PickListItem.objects.bulk_create(items)

  order_ids = [oid for data in grouped.values() for oid in data["order_ids"]]
  Order.objects.filter(id__in=order_ids).update(
    status=Order.Status.IN_PICKING,
    pick_list=pick_list,
  )

  return pick_list


@transaction.atomic
def delete_active_pick_list(
  seller: Seller,
  *,
  pick_list_id: int | None = None,
  user=None,
) -> dict:
  """Удалить активный лист подбора и отвязать заказы (если сканирование не начато)."""
  qs = PickList.objects.filter(seller=seller, is_completed=False)
  if pick_list_id:
    pick_list = qs.filter(pk=pick_list_id).first()
  else:
    pick_list = qs.order_by("-created_at").first()

  if not pick_list:
    raise PickListError("Активный лист подбора не найден")

  orders = list(Order.objects.filter(pick_list=pick_list))
  blocked = [
    order
    for order in orders
    if order.status
    not in (Order.Status.NEW, Order.Status.IN_PICKING)
  ]
  if blocked:
    raise PickListError(
      "Нельзя удалить лист: часть заказов уже прошла сканирование или печать стикера",
    )

  unlocked = 0
  for order in orders:
    order.pick_list = None
    update_fields = ["pick_list", "updated_at"]
    wb_status = (order.wb_supplier_status or "").strip()
    if order.status == Order.Status.IN_PICKING and wb_status in ("", WB_SUPPLIER_NEW):
      order.status = Order.Status.NEW
      update_fields.append("status")
    order.save(update_fields=update_fields)
    unlocked += 1

  deleted_id = pick_list.id
  pick_list.delete()

  return {
    "deleted_pick_list_id": deleted_id,
    "orders_unlocked": unlocked,
  }
