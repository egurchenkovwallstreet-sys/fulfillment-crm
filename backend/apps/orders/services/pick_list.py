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
  orders = list(
    Order.objects.filter(
      seller=seller,
      status=Order.Status.NEW,
      wb_supplier_status__in=[WB_SUPPLIER_NEW, ""],
    ).select_related("product", "product__cell")
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
