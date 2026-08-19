from django.utils import timezone

from apps.integrations.models import AuditLog
from apps.integrations.wb_client import WBApiError, WBClient
from apps.integrations.wb_crypto import TokenCryptoError, decrypt_token
from apps.orders.services.wb_status import (
  WB_SUPPLIER_ASSEMBLY,
  WB_SUPPLIER_DELIVERY,
  WB_SUPPLIER_LABELS,
  WB_SUPPLIER_NEW,
)
from apps.orders.models import Order, PickList
from apps.sellers.models import Seller
from apps.orders.services.pick_list import PickListError, generate_pick_list


class AssemblyError(Exception):
  pass


def _get_client(seller: Seller) -> WBClient:
  if not seller.wb_api_token_encrypted:
    raise AssemblyError(f"У селлера «{seller.company_name}» не задан токен WB")
  try:
    token = decrypt_token(seller.wb_api_token_encrypted)
  except TokenCryptoError as exc:
    raise AssemblyError(str(exc)) from exc
  return WBClient(token)


def fetch_stickers_for_orders(seller: Seller, orders: list[Order], *, user=None) -> int:
  if not orders:
    return 0

  client = _get_client(seller)
  wb_ids = [order.wb_order_id for order in orders]

  try:
    stickers = client.fetch_order_stickers(wb_ids)
  except WBApiError as exc:
    AuditLog.objects.create(
      user=user,
      seller=seller,
      action_type=AuditLog.ActionType.API_ERROR,
      message=f"Ошибка получения стикеров WB: {exc}",
      details={"status_code": exc.status_code},
    )
    raise AssemblyError(str(exc)) from exc

  sticker_map = {int(item.get("orderId")): item for item in stickers if item.get("orderId")}

  updated = 0
  now = timezone.now()
  for order in orders:
    data = sticker_map.get(order.wb_order_id)
    if not data:
      continue
    order.sticker_file = data.get("file") or ""
    order.sticker_part_a = str(data.get("partA") or "")
    order.sticker_part_b = str(data.get("partB") or "")
    order.has_sticker = bool(order.sticker_file)
    order.sticker_fetched_at = now
    order.save(
      update_fields=[
        "sticker_file",
        "sticker_part_a",
        "sticker_part_b",
        "has_sticker",
        "sticker_fetched_at",
        "updated_at",
      ]
    )
    updated += 1

  return updated


def start_assembly(seller: Seller, *, user=None) -> dict:
  """Начать сборку: лист подбора + автозагрузка стикеров WB."""
  pick_list = generate_pick_list(seller, user=user)
  orders = list(
    Order.objects.filter(pick_list=pick_list, status=Order.Status.IN_PICKING)
  )

  stickers_fetched = 0
  sticker_errors = ""
  try:
    stickers_fetched = fetch_stickers_for_orders(seller, orders, user=user)
  except AssemblyError as exc:
    sticker_errors = str(exc)

  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.ASSEMBLY,
    message=(
      f"Начата сборка: лист #{pick_list.id}, заказов {len(orders)}, "
      f"стикеров {stickers_fetched}"
    ),
    details={
      "pick_list_id": pick_list.id,
      "orders_count": len(orders),
      "stickers_fetched": stickers_fetched,
      "sticker_errors": sticker_errors,
    },
  )

  return {
    "pick_list_id": pick_list.id,
    "orders_count": len(orders),
    "stickers_fetched": stickers_fetched,
    "sticker_errors": sticker_errors,
  }


def scan_and_print(seller: Seller, scan_value: str, *, user=None) -> Order:
  """Найти заказ по скану и подготовить к печати стикера."""
  scan_value = scan_value.strip()
  if not scan_value:
    raise AssemblyError("Пустой штрихкод")

  orders_qs = Order.objects.filter(
    seller=seller,
    status__in=[Order.Status.IN_PICKING, Order.Status.ASSEMBLED],
  )

  order = orders_qs.filter(barcode=scan_value).first()
  if not order and scan_value.isdigit():
    order = orders_qs.filter(wb_order_id=int(scan_value)).first()

  if not order:
    raise AssemblyError("Заказ не найден в текущей сборке")

  if not order.has_sticker or not order.sticker_file:
    raise AssemblyError("Стикер для заказа ещё не загружен из WB")

  order.status = Order.Status.LABEL_PRINTED
  order.save(update_fields=["status", "updated_at"])

  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.LABEL_PRINT,
    message=f"Печать стикера заказа WB #{order.wb_order_id}",
    details={"order_id": order.id, "barcode": order.barcode},
  )

  return order


def get_seller_stage_counts(seller: Seller) -> dict[str, int]:
  qs = Order.objects.filter(seller=seller)
  active = qs.exclude(status=Order.Status.CANCELLED)
  return {
    "new": active.filter(wb_supplier_status=WB_SUPPLIER_NEW).count(),
    "in_picking": active.filter(wb_supplier_status=WB_SUPPLIER_ASSEMBLY).count(),
    "in_delivery": active.filter(wb_supplier_status=WB_SUPPLIER_DELIVERY).count(),
    "assembled": active.filter(status=Order.Status.ASSEMBLED).count(),
    "label_printed": active.filter(status=Order.Status.LABEL_PRINTED).count(),
    "marked": active.filter(status=Order.Status.MARKED).count(),
    "in_supply": active.filter(status=Order.Status.IN_SUPPLY).count(),
    "shipped": qs.filter(status=Order.Status.SHIPPED).count(),
    "cancelled": qs.filter(status=Order.Status.CANCELLED).count(),
  }


def get_wb_stage_label(wb_supplier_status: str) -> str:
  return WB_SUPPLIER_LABELS.get(wb_supplier_status, wb_supplier_status or "—")
