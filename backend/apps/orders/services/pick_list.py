from collections import defaultdict
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.orders.models import Order, PickList, PickListItem, Supply
from apps.orders.services.wb_status import WB_STAGE_QUERIES, WB_SUPPLIER_NEW
from apps.sellers.models import Seller, SellerWarehouse
from apps.sellers.services.warehouse_filter import (
  filter_orders_for_assembly,
  filter_supplies_for_assembly,
  get_enabled_wb_warehouse_ids,
)
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


def _warehouse_label(seller: Seller, wb_warehouse_id: int) -> str:
  wh = SellerWarehouse.objects.filter(
    seller=seller,
    wb_warehouse_id=wb_warehouse_id,
  ).first()
  if wh and wh.name:
    return wh.name
  return f"Склад #{wb_warehouse_id}"


def _group_orders_by_warehouse(
  seller: Seller,
  orders: list[Order],
) -> dict[int, list[Order]]:
  enabled = get_enabled_wb_warehouse_ids(seller)
  grouped: dict[int, list[Order]] = defaultdict(list)
  for order in orders:
    wh_id = order.wb_warehouse_id
    if wh_id is None:
      continue
    if enabled and wh_id not in enabled:
      continue
    grouped[int(wh_id)].append(order)
  return grouped


def active_wb_pick_lists(seller: Seller) -> list[PickList]:
  return list(
    PickList.objects.filter(seller=seller, is_completed=False, marketplace=MARKETPLACE_WB)
    .prefetch_related("items__cell", "items__product")
    .order_by("warehouse_name", "-created_at")
  )


def archived_wb_pick_lists(seller: Seller, *, days: int = 10) -> list[PickList]:
  """Завершённые листы подбора за последние N дней."""
  since = timezone.now() - timedelta(days=days)
  return list(
    PickList.objects.filter(
      seller=seller,
      is_completed=True,
      marketplace=MARKETPLACE_WB,
      created_at__gte=since,
    )
    .prefetch_related("items__cell", "items__product")
    .order_by("-created_at")
  )


def _active_wb_pick_list_for_warehouse(
  seller: Seller,
  wb_warehouse_id: int,
) -> PickList | None:
  return (
    PickList.objects.filter(
      seller=seller,
      is_completed=False,
      marketplace=MARKETPLACE_WB,
      wb_warehouse_id=wb_warehouse_id,
    )
    .prefetch_related("items__cell", "items__product")
    .order_by("-created_at")
    .first()
  )


def _crm_assembly_supply_order_ids(seller: Seller) -> set[int]:
  """Заказы в активных поставках CRM — только они попадают в лист «На сборке»."""
  supplies = filter_supplies_for_assembly(
    Supply.objects.filter(
      seller=seller,
      status__in=(Supply.Status.FORMING, Supply.Status.READY),
    ),
    seller,
  )
  return set(
    Order.objects.filter(
      supplies__in=supplies,
      assembly_hidden=False,
    ).values_list("id", flat=True)
  )


def _orders_for_pick_list(seller: Seller, *, stage: str = "new"):
  if stage == "confirm":
    crm_order_ids = _crm_assembly_supply_order_ids(seller)
    if not crm_order_ids:
      return []
    qs = (
      filter_orders_for_assembly(
        Order.objects.filter(
          seller=seller,
          assembly_hidden=False,
          id__in=crm_order_ids,
        ).filter(WB_STAGE_QUERIES["confirm"]()),
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


def _pick_list_meta(
  seller: Seller,
  *,
  stage: str,
  items: list[dict],
  orders_without_product: int,
  warehouse_name: str,
  wb_warehouse_id: int | None = None,
) -> dict:
  total_quantity = sum(item["quantity"] for item in items)
  stage_title = "На сборке" if stage == "confirm" else "Новые"

  return {
    "items_count": len(items),
    "total_quantity": total_quantity,
    "warehouse_label": warehouse_name,
    "warehouse_name": warehouse_name,
    "wb_warehouse_id": wb_warehouse_id,
    "stage_label": stage_title,
    "orders_in_list": total_quantity,
    "orders_skipped": orders_without_product,
    "orders_without_cell": orders_without_product,
  }


def _build_pick_list_preview_payload(
  seller: Seller,
  *,
  stage: str,
  wb_warehouse_id: int,
  warehouse_name: str,
  items: list[dict],
  orders_without_product: int,
  pick_list_id: int = 0,
) -> dict:
  meta = _pick_list_meta(
    seller,
    stage=stage,
    items=items,
    orders_without_product=orders_without_product,
    warehouse_name=warehouse_name,
    wb_warehouse_id=wb_warehouse_id,
  )
  public_items = [
    {k: v for k, v in item.items() if k not in ("order_ids", "product", "cell")}
    for item in items
  ]
  return {
    "id": pick_list_id,
    "preview": pick_list_id == 0,
    "stage": stage,
    "seller": seller.id,
    "seller_name": seller.company_name,
    "is_completed": False,
    "created_at": timezone.now().isoformat(),
    "items": public_items,
    **meta,
  }


def preview_pick_lists(seller: Seller, *, stage: str = "new", user=None) -> list[dict]:
  """Листы подбора по складам для PDF — без привязки заказов."""
  orders = _orders_for_pick_list(seller, stage=stage)
  by_warehouse = _group_orders_by_warehouse(seller, orders)
  if not by_warehouse:
    stage_label = "на сборке" if stage == "confirm" else "новых"
    raise PickListError(
      f"Нет {stage_label} заказов для листа подбора. Включите склад и обновите заказы из WB.",
    )

  previews: list[dict] = []
  for wb_warehouse_id in sorted(by_warehouse.keys()):
    wh_orders = by_warehouse[wb_warehouse_id]
    items, orders_without_product = _group_orders_for_pick_list(seller, wh_orders)
    previews.append(
      _build_pick_list_preview_payload(
        seller,
        stage=stage,
        wb_warehouse_id=wb_warehouse_id,
        warehouse_name=_warehouse_label(seller, wb_warehouse_id),
        items=items,
        orders_without_product=orders_without_product,
      ),
    )
  return previews


def preview_pick_list(seller: Seller, *, stage: str = "new", user=None) -> dict:
  previews = preview_pick_lists(seller, stage=stage, user=user)
  if len(previews) == 1:
    return previews[0]
  total_quantity = sum(item["total_quantity"] for item in previews)
  return {
    "id": 0,
    "preview": True,
    "stage": stage,
    "seller": seller.id,
    "seller_name": seller.company_name,
    "is_completed": False,
    "created_at": timezone.now().isoformat(),
    "items": [],
    "pick_lists": previews,
    "items_count": sum(item["items_count"] for item in previews),
    "total_quantity": total_quantity,
    "warehouse_label": ", ".join(item["warehouse_name"] for item in previews),
    "orders_in_list": total_quantity,
  }


def _active_wb_pick_list(seller: Seller) -> PickList | None:
  return (
    PickList.objects.filter(seller=seller, is_completed=False, marketplace="wb")
    .prefetch_related("items__cell", "items__product")
    .order_by("-created_at")
    .first()
  )


def _pick_list_has_scanned_orders(pick_list: PickList) -> bool:
  return Order.objects.filter(pick_list=pick_list).exclude(
    status__in=[Order.Status.NEW, Order.Status.IN_PICKING],
  ).exists()


def _fill_pick_list_items(pick_list: PickList, items: list[dict]) -> list[int]:
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
  return order_ids


def _create_or_refresh_warehouse_pick_list(
  seller: Seller,
  *,
  wb_warehouse_id: int,
  wh_orders: list[Order],
  stage: str,
  force: bool,
  user=None,
) -> PickList:
  warehouse_name = _warehouse_label(seller, wb_warehouse_id)
  existing = _active_wb_pick_list_for_warehouse(seller, wb_warehouse_id)

  if existing and existing.items.exists() and not force:
    return existing

  if stage == "new" and not force:
    wh_orders = [order for order in wh_orders if order.pick_list_id is None]

  if not wh_orders:
    if existing and force and not _pick_list_has_scanned_orders(existing):
      delete_active_pick_list(seller, pick_list_id=existing.id, user=user)
    raise PickListError(
      f"Нет заказов для склада «{warehouse_name}» на вкладке "
      f"{'«На сборке»' if stage == 'confirm' else '«Новые»'}.",
    )

  items, _orders_without_product = _group_orders_for_pick_list(seller, wh_orders)

  pick_list = existing
  if pick_list and force:
    if _pick_list_has_scanned_orders(pick_list):
      pick_list.items.all().delete()
      keep_ids = {order_id for data in items for order_id in data["order_ids"]}
      Order.objects.filter(pick_list=pick_list).exclude(id__in=keep_ids).update(pick_list=None)
    else:
      delete_active_pick_list(seller, pick_list_id=pick_list.id, user=user)
      pick_list = None

  if pick_list is None:
    pick_list = PickList.objects.create(
      seller=seller,
      marketplace=MARKETPLACE_WB,
      wb_warehouse_id=wb_warehouse_id,
      warehouse_name=warehouse_name,
    )
  else:
    pick_list.warehouse_name = warehouse_name
    pick_list.wb_warehouse_id = wb_warehouse_id
    pick_list.save(update_fields=["warehouse_name", "wb_warehouse_id"])

  order_ids = _fill_pick_list_items(pick_list, items)
  qs = Order.objects.filter(id__in=order_ids)
  if stage == "new":
    qs.update(status=Order.Status.IN_PICKING, pick_list=pick_list)
  else:
    qs.update(pick_list=pick_list)

  return pick_list


@transaction.atomic
def generate_pick_lists(
  seller: Seller,
  *,
  user=None,
  force: bool = False,
  stage: str = "new",
) -> list[PickList]:
  """Отдельный лист подбора на каждый включённый FBS-склад с заказами."""
  if stage not in ("new", "confirm"):
    stage = "new"

  orders = list(_orders_for_pick_list(seller, stage=stage))
  by_warehouse = _group_orders_by_warehouse(seller, orders)
  if not by_warehouse:
    stage_label = "на сборке" if stage == "confirm" else "новых"
    raise PickListError(
      f"Нет {stage_label} заказов для листа подбора. "
      "Включите склад FBS и обновите заказы.",
    )

  if force:
    for stale in active_wb_pick_lists(seller):
      if _pick_list_has_scanned_orders(stale):
        continue
      delete_active_pick_list(seller, pick_list_id=stale.id, user=user)

  pick_lists: list[PickList] = []
  errors: list[str] = []
  for wb_warehouse_id in sorted(by_warehouse.keys()):
    try:
      pick_lists.append(
        _create_or_refresh_warehouse_pick_list(
          seller,
          wb_warehouse_id=wb_warehouse_id,
          wh_orders=by_warehouse[wb_warehouse_id],
          stage=stage,
          force=force,
          user=user,
        ),
      )
    except PickListError as exc:
      errors.append(str(exc))

  if not pick_lists:
    raise PickListError(errors[0] if errors else "Не удалось сформировать листы подбора")

  return pick_lists


@transaction.atomic
def generate_pick_list(
  seller: Seller,
  *,
  user=None,
  force: bool = False,
  stage: str = "new",
) -> PickList:
  """Сохранить листы подбора по складам; вернуть первый для обратной совместимости."""
  pick_lists = generate_pick_lists(
    seller,
    user=user,
    force=force,
    stage=stage,
  )
  return pick_lists[0]


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
