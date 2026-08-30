from collections import defaultdict

from django.db import transaction
from django.utils import timezone

from apps.orders.models import Order, PickList, PickListItem
from apps.orders.services.wb_status import WB_STAGE_QUERIES, WB_SUPPLIER_NEW
from apps.sellers.models import Seller
from apps.sellers.services.warehouse_filter import filter_orders_for_assembly
from apps.integrations.marketplace import WB as MARKETPLACE_WB
from apps.warehouse.models import Product


class PickListError(Exception):
  pass


def _product_size_label(product: Product | None) -> str:
  if not product:
    return ""
  return (product.tech_size or product.wb_size or "").strip()


def _product_wb_article(product: Product | None) -> str:
  if not product:
    return ""
  if product.wb_nm_id:
    return str(product.wb_nm_id)
  return (product.vendor_code or "").strip()


def _cell_sort_key(cell_number: str) -> tuple[int, int, str]:
  if not cell_number or cell_number == "—":
    return (1, 999999, "")
  if cell_number.isdigit():
    return (0, int(cell_number), "")
  return (0, 999998, cell_number)


def _orders_for_pick_list(seller: Seller, *, stage: str = "new"):
  if stage == "confirm":
    qs = (
      filter_orders_for_assembly(
        Order.objects.filter(seller=seller, assembly_hidden=False).filter(
          WB_STAGE_QUERIES["confirm"](),
        ),
        seller,
      )
      .exclude(
        status__in=[
          Order.Status.CANCELLED,
          Order.Status.SHIPPED,
        ],
      )
      .select_related("product", "product__cell")
    )
  else:
    from apps.orders.services.supply_flow import new_stage_orders_queryset

    qs = new_stage_orders_queryset(seller).select_related("product", "product__cell")

  return list(qs)


def _products_by_barcode(seller: Seller, barcodes: set[str]) -> dict[str, Product]:
  if not barcodes:
    return {}
  products = Product.objects.filter(
    seller=seller,
    barcode__in=barcodes,
    marketplace=MARKETPLACE_WB,
  ).select_related("cell")
  return {product.barcode: product for product in products}


def _optional_link_orders_to_products(
  seller: Seller,
  orders: list[Order],
  products_by_barcode: dict[str, Product],
) -> None:
  """Привязать product к заказам одним bulk_update — не блокирует лист, если товара нет."""
  to_update: list[Order] = []
  for order in orders:
    if order.product_id:
      continue
    product = products_by_barcode.get(order.barcode)
    if not product:
      continue
    order.product = product
    order.product_id = product.id
    to_update.append(order)
  if to_update:
    Order.objects.bulk_update(to_update, ["product", "updated_at"], batch_size=500)


def _group_orders_for_pick_list(
  seller: Seller,
  orders: list[Order],
) -> tuple[list[dict], int]:
  """Сгруппировать заказы для листа. Заказы без товара в CRM — по баркоду, ячейка «—»."""
  barcodes = {order.barcode for order in orders if order.barcode}
  products_by_barcode = _products_by_barcode(seller, barcodes)
  _optional_link_orders_to_products(seller, orders, products_by_barcode)

  grouped: dict[tuple[int, int, str], dict] = defaultdict(
    lambda: {
      "quantity": 0,
      "order_ids": [],
      "product": None,
      "cell": None,
      "barcode": "",
    }
  )
  orders_without_product = 0

  for order in orders:
    product = order.product
    if not order.product_id and order.barcode in products_by_barcode:
      product = products_by_barcode[order.barcode]
      order.product = product

    if product:
      key = (product.cell_id, product.id, order.barcode)
      grouped[key]["product"] = product
      grouped[key]["cell"] = product.cell
    else:
      orders_without_product += 1
      key = (0, 0, order.barcode)
      grouped[key]["product"] = None
      grouped[key]["cell"] = None

    grouped[key]["barcode"] = order.barcode
    grouped[key]["quantity"] += 1
    grouped[key]["order_ids"].append(order.id)

  preview_items: list[dict] = []
  for index, (_key, data) in enumerate(
    sorted(
      grouped.items(),
      key=lambda entry: _cell_sort_key(
        str(entry[1]["cell"].number) if entry[1]["cell"] else "—"
      ),
    ),
    start=1,
  ):
    product = data["product"]
    cell_number = str(data["cell"].number) if data["cell"] else "—"
    preview_items.append({
      "id": index,
      "cell_number": cell_number,
      "barcode": data["barcode"],
      "product_name": product.name if product else "—",
      "wb_nm_id": product.wb_nm_id if product else None,
      "wb_article": _product_wb_article(product) or "—",
      "tech_size": _product_size_label(product) or "—",
      "quantity": data["quantity"],
      "picked_quantity": 0,
      "order_ids": data["order_ids"],
      "product": product,
      "cell": data["cell"],
    })

  return preview_items, orders_without_product


def _pick_list_meta(seller: Seller, *, stage: str, items: list[dict], orders_without_product: int) -> dict:
  total_quantity = sum(item["quantity"] for item in items)
  enabled_names = list(
    seller.wb_warehouses.filter(is_enabled=True).values_list("name", flat=True)
  )
  warehouse_label = ", ".join(name for name in enabled_names if name) or "включённые склады"
  stage_title = "На сборке" if stage == "confirm" else "Новые"

  return {
    "items_count": len(items),
    "total_quantity": total_quantity,
    "warehouse_label": warehouse_label,
    "stage_label": stage_title,
    "orders_in_list": total_quantity,
    "orders_skipped": orders_without_product,
    "orders_without_cell": orders_without_product,
  }


def preview_pick_list(seller: Seller, *, stage: str = "new", user=None) -> dict:
  """Лист подбора для PDF — без привязки заказов и без отправки в WB."""
  orders = _orders_for_pick_list(seller, stage=stage)
  if not orders:
    stage_label = "на сборке" if stage == "confirm" else "новых"
    raise PickListError(
      f"Нет {stage_label} заказов для листа подбора. Выберите склад и обновите заказы из WB.",
    )

  items, orders_without_product = _group_orders_for_pick_list(seller, orders)
  meta = _pick_list_meta(seller, stage=stage, items=items, orders_without_product=orders_without_product)

  public_items = [{k: v for k, v in item.items() if k not in ("order_ids", "product", "cell")} for item in items]

  return {
    "id": 0,
    "preview": True,
    "stage": stage,
    "seller": seller.id,
    "seller_name": seller.company_name,
    "is_completed": False,
    "created_at": timezone.now().isoformat(),
    "items": public_items,
    **meta,
  }


@transaction.atomic
def generate_pick_list(seller: Seller, *, user=None, force: bool = False) -> PickList:
  existing = (
    PickList.objects.filter(seller=seller, is_completed=False, marketplace="wb")
    .prefetch_related("items__cell", "items__product")
    .order_by("-created_at")
    .first()
  )
  if existing and existing.items.exists() and not force:
    return existing
  if existing and force:
    delete_active_pick_list(seller, pick_list_id=existing.id, user=user)

  orders = [
    order for order in _orders_for_pick_list(seller, stage="new")
    if order.pick_list_id is None
  ]

  if not orders:
    raise PickListError("Нет новых заказов для формирования листа подбора")

  items, _orders_without_product = _group_orders_for_pick_list(seller, orders)

  pick_list = PickList.objects.create(seller=seller, marketplace="wb")
  db_items: list[PickListItem] = []
  order_ids: list[int] = []

  for data in items:
    db_items.append(
      PickListItem(
        pick_list=pick_list,
        cell=data["cell"],
        product=data["product"],
        barcode=data["barcode"],
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
