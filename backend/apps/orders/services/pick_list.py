from collections import defaultdict

from django.db import transaction
from django.utils import timezone

from apps.orders.models import Order, PickList, PickListItem
from apps.orders.services.wb_status import WB_SUPPLIER_NEW
from apps.sellers.models import Seller
from apps.warehouse.models import Product


class PickListError(Exception):
  pass


def _orders_for_pick_list(seller: Seller):
  from apps.orders.services.supply_flow import new_stage_orders_queryset

  return list(
    new_stage_orders_queryset(seller)
    .select_related("product", "product__cell")
  )


def _group_orders_for_pick_list(
  seller: Seller,
  orders: list[Order],
) -> tuple[list[dict], list[int]]:
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

  items: list[dict] = []
  for index, (key, data) in enumerate(
    sorted(grouped.items(), key=lambda entry: int(entry[1]["cell"].number)),
    start=1,
  ):
    _cell_id, _product_id, barcode = key
    items.append({
      "id": index,
      "cell_number": str(data["cell"].number),
      "barcode": barcode,
      "product_name": data["product"].name,
      "quantity": data["quantity"],
      "picked_quantity": 0,
    })

  return items, missing_product


def preview_pick_list(seller: Seller, *, user=None) -> dict:
  """Лист подбора для PDF по включённым складам — без привязки заказов и WB."""
  orders = _orders_for_pick_list(seller)
  if not orders:
    raise PickListError(
      "Нет новых заказов для листа подбора. Выберите склад и обновите заказы из WB.",
    )

  items, missing_product = _group_orders_for_pick_list(seller, orders)
  if not items:
    raise PickListError(
      "Ни один заказ не привязан к товару на складе. "
      f"Без товара: {len(missing_product)} зак.",
    )

  total_quantity = sum(item["quantity"] for item in items)
  enabled_names = list(
    seller.wb_warehouses.filter(is_enabled=True).values_list("name", flat=True)
  )
  warehouse_label = ", ".join(name for name in enabled_names if name) or "включённые склады"

  return {
    "id": 0,
    "preview": True,
    "seller": seller.id,
    "seller_name": seller.company_name,
    "is_completed": False,
    "created_at": timezone.now().isoformat(),
    "items": items,
    "items_count": len(items),
    "total_quantity": total_quantity,
    "warehouse_label": warehouse_label,
    "orders_in_list": total_quantity,
    "orders_skipped": len(missing_product),
  }


@transaction.atomic
def generate_pick_list(seller: Seller, *, user=None) -> PickList:
  existing = (
    PickList.objects.filter(seller=seller, is_completed=False)
    .prefetch_related("items__cell", "items__product")
    .first()
  )
  if existing and existing.items.exists():
    return existing

  orders = [
    order for order in _orders_for_pick_list(seller)
    if order.pick_list_id is None
  ]

  if not orders:
    raise PickListError("Нет новых заказов для формирования листа подбора")

  pick_list = PickList.objects.create(seller=seller)
  items_data, missing_product = _group_orders_for_pick_list(seller, orders)

  if not items_data:
    pick_list.delete()
    raise PickListError(
      "Ни один заказ не привязан к товару на складе. "
      f"Без товара: {len(missing_product)} зак.",
    )

  order_ids: list[int] = []
  grouped: dict[tuple[int, int, str], dict] = defaultdict(
    lambda: {"quantity": 0, "order_ids": []}
  )
  for order in orders:
    product = order.product
    if not product:
      continue
    key = (product.cell_id, product.id, order.barcode)
    grouped[key]["quantity"] += 1
    grouped[key]["order_ids"].append(order.id)
    grouped[key]["product"] = product
    grouped[key]["cell"] = product.cell

  db_items: list[PickListItem] = []
  for (_cell_id, _product_id, barcode), data in sorted(
    grouped.items(),
    key=lambda entry: int(entry[1]["cell"].number),
  ):
    db_items.append(
      PickListItem(
        pick_list=pick_list,
        cell=data["cell"],
        product=data["product"],
        barcode=barcode,
        quantity=data["quantity"],
      )
    )
    order_ids.extend(data["order_ids"])

  PickListItem.objects.bulk_create(db_items)

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
