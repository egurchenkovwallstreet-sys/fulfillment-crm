from django.utils import timezone

from apps.integrations.models import AuditLog
from apps.integrations.wb_client import WBApiError, WBClient
from apps.integrations.wb_crypto import TokenCryptoError, decrypt_token
from apps.orders.services.wb_status import (
  WB_SUPPLIER_ASSEMBLY,
  WB_SUPPLIER_DELIVERY,
  WB_SUPPLIER_LABELS,
  WB_SUPPLIER_NEW,
  wb_in_delivery_q,
)
from apps.orders.models import Order, PickList
from apps.sellers.services.warehouse_filter import filter_orders_for_seller
from apps.orders.services.marking import parse_wb_marking_error, validate_marking_code
from apps.sellers.models import Seller
from apps.orders.services.pick_list import PickListError, generate_pick_list
from apps.warehouse.models import Product
from apps.warehouse.services.marking_lookup import resolve_product_requires_marking


class AssemblyError(Exception):
  def __init__(self, message: str, *, code: str = "error"):
    super().__init__(message)
    self.code = code


def _get_client(seller: Seller) -> WBClient:
  if not seller.wb_api_token_encrypted:
    raise AssemblyError(f"У селлера «{seller.company_name}» не задан токен WB")
  try:
    token = decrypt_token(seller.wb_api_token_encrypted)
  except TokenCryptoError as exc:
    raise AssemblyError(str(exc)) from exc
  return WBClient(token)


def _find_active_order(seller: Seller, scan_value: str) -> Order:
  scan_value = scan_value.strip()
  if not scan_value:
    raise AssemblyError("Пустой штрихкод")

  orders_qs = filter_orders_for_seller(
    Order.objects.filter(
      seller=seller,
      status__in=[Order.Status.IN_PICKING, Order.Status.ASSEMBLED],
    ).select_related("product"),
    seller,
  )

  order = orders_qs.filter(barcode=scan_value).first()
  if not order and scan_value.isdigit():
    order = orders_qs.filter(wb_order_id=int(scan_value)).first()

  if not order:
    raise AssemblyError(
      "Заказ не найден в текущей сборке. "
      "Проверьте баркод или обновите заказы из WB.",
      code="order_not_found",
    )
  return order


def _order_requires_marking(order: Order) -> bool:
  return resolve_product_requires_marking(order.product, order.barcode, order.seller)


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


def scan_order_barcode(seller: Seller, scan_value: str, *, user=None) -> dict:
  """
  Шаг 1: скан баркода заказа.
  — без ЧЗ: сразу LABEL_PRINTED + печать;
  — с ЧЗ: ждём скан DataMatrix (стикер не печатаем).
  """
  order = _find_active_order(seller, scan_value)

  if not order.has_sticker or not order.sticker_file:
    raise AssemblyError(
      f"Стикер для заказа WB #{order.wb_order_id} ещё не загружен. "
      "Нажмите «Начать сборку» или обновите заказы.",
      code="no_sticker",
    )

  if not order.product:
    product = Product.objects.filter(seller=seller, barcode=order.barcode).first()
    if product:
      order.product = product
      order.save(update_fields=["product", "updated_at"])

  requires_marking = _order_requires_marking(order)

  if not requires_marking:
    order.status = Order.Status.LABEL_PRINTED
    order.save(update_fields=["status", "updated_at"])
    AuditLog.objects.create(
      user=user,
      seller=seller,
      action_type=AuditLog.ActionType.LABEL_PRINT,
      message=f"Печать стикера заказа WB #{order.wb_order_id}",
      details={"order_id": order.id, "barcode": order.barcode},
    )
    return {
      "action": "print",
      "requires_marking": False,
      "order": order,
    }

  order.status = Order.Status.ASSEMBLED
  order.save(update_fields=["status", "updated_at"])

  return {
    "action": "await_marking",
    "requires_marking": True,
    "order": order,
    "message": (
      f"Заказ WB #{order.wb_order_id} требует Честный знак. "
      "Отсканируйте DataMatrix с упаковки."
    ),
  }


def bind_marking_and_print(
  seller: Seller,
  order_id: int,
  marking_code: str,
  *,
  user=None,
) -> Order:
  """Шаг 2: скан ЧЗ → привязка в WB → MARKED → печать стикера."""
  try:
    order = Order.objects.select_related("product").get(
      pk=order_id,
      seller=seller,
    )
  except Order.DoesNotExist as exc:
    raise AssemblyError("Заказ не найден", code="order_not_found") from exc

  if order.status not in (Order.Status.IN_PICKING, Order.Status.ASSEMBLED):
    raise AssemblyError(
      f"Заказ WB #{order.wb_order_id} не ожидает привязку ЧЗ "
      f"(статус: {order.get_status_display()}). Нажмите «Заменить товар» для сброса.",
      code="invalid_status",
    )

  if not _order_requires_marking(order):
    raise AssemblyError(
      "Для этого заказа маркировка ЧЗ не требуется",
      code="marking_not_required",
    )

  if not order.has_sticker or not order.sticker_file:
    raise AssemblyError(
      "Стикер не загружен — начните сборку заново",
      code="no_sticker",
    )

  normalized, validation_error = validate_marking_code(marking_code)
  if validation_error:
    raise AssemblyError(validation_error, code="invalid_marking_code")

  duplicate = Order.objects.filter(
    marking_code=normalized,
    marking_bound=True,
  ).exclude(pk=order.pk).exists()
  if duplicate:
    raise AssemblyError(
      "Этот код ЧЗ уже использован для другого заказа в CRM. "
      "Возьмите другой экземпляр товара.",
      code="duplicate_marking",
    )

  client = _get_client(seller)
  try:
    client.bind_order_sgtin(order.wb_order_id, [normalized])
  except WBApiError as exc:
    AuditLog.objects.create(
      user=user,
      seller=seller,
      action_type=AuditLog.ActionType.API_ERROR,
      message=f"Ошибка привязки ЧЗ WB #{order.wb_order_id}: {exc}",
      details={"order_id": order.id, "status_code": exc.status_code},
    )
    raise AssemblyError(parse_wb_marking_error(exc), code="wb_bind_failed") from exc

  order.marking_code = normalized
  order.marking_bound = True
  order.status = Order.Status.MARKED
  order.save(update_fields=["marking_code", "marking_bound", "status", "updated_at"])

  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.MARKING,
    message=f"ЧЗ привязан к заказу WB #{order.wb_order_id}",
    details={"order_id": order.id, "barcode": order.barcode},
  )

  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.LABEL_PRINT,
    message=f"Печать стикера после ЧЗ, заказ WB #{order.wb_order_id}",
    details={"order_id": order.id, "barcode": order.barcode},
  )

  return order


def replace_order_item(seller: Seller, order_id: int, *, user=None) -> Order:
  """Сброс заказа для замены товара / повторной сборки."""
  try:
    order = Order.objects.get(pk=order_id, seller=seller)
  except Order.DoesNotExist as exc:
    raise AssemblyError("Заказ не найден", code="order_not_found") from exc

  if order.status not in (
    Order.Status.IN_PICKING,
    Order.Status.ASSEMBLED,
    Order.Status.LABEL_PRINTED,
  ):
    raise AssemblyError(
      f"Заказ WB #{order.wb_order_id} нельзя сбросить "
      f"(статус: {order.get_status_display()})",
      code="invalid_status",
    )

  if order.marking_bound and order.marking_code:
    client = _get_client(seller)
    try:
      client.delete_order_meta(order.wb_order_id, key="sgtin")
    except WBApiError as exc:
      raise AssemblyError(
        f"Не удалось снять привязку ЧЗ в WB: {parse_wb_marking_error(exc)}. "
        "Проверьте заказ в личном кабинете WB.",
        code="wb_unbind_failed",
      ) from exc

  order.marking_code = ""
  order.marking_bound = False
  order.status = Order.Status.IN_PICKING
  order.save(
    update_fields=["marking_code", "marking_bound", "status", "updated_at"],
  )

  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.ASSEMBLY,
    message=f"Замена товара: сброс заказа WB #{order.wb_order_id}",
    details={"order_id": order.id, "barcode": order.barcode},
  )

  return order


def scan_and_print(seller: Seller, scan_value: str, *, user=None) -> Order:
  """Обратная совместимость: только заказы без ЧЗ."""
  result = scan_order_barcode(seller, scan_value, user=user)
  if result["action"] == "await_marking":
    raise AssemblyError(
      result["message"],
      code="await_marking",
    )
  return result["order"]


def get_seller_stage_counts(seller: Seller) -> dict[str, int]:
  """Единый источник счётчиков: БД + фильтр включённых складов WB."""
  qs = filter_orders_for_seller(Order.objects.filter(seller=seller), seller)
  active = qs.exclude(status=Order.Status.CANCELLED)

  return {
    "new": active.filter(wb_supplier_status=WB_SUPPLIER_NEW).count(),
    "in_picking": active.filter(wb_supplier_status=WB_SUPPLIER_ASSEMBLY).count(),
    "in_delivery": active.filter(wb_in_delivery_q()).count(),
    "assembled": active.filter(status=Order.Status.ASSEMBLED).count(),
    "label_printed": active.filter(status=Order.Status.LABEL_PRINTED).count(),
    "marked": active.filter(status=Order.Status.MARKED).count(),
    "in_supply": active.filter(status=Order.Status.IN_SUPPLY).count(),
    "shipped": qs.filter(status=Order.Status.SHIPPED).count(),
    "cancelled": qs.filter(status=Order.Status.CANCELLED).count(),
  }


def get_wb_stage_label(wb_supplier_status: str) -> str:
  return WB_SUPPLIER_LABELS.get(wb_supplier_status, wb_supplier_status or "—")
