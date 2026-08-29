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
from apps.orders.models import Order, PickList, PickListItem, Supply
from apps.sellers.services.warehouse_filter import filter_orders_for_seller
from apps.orders.services.marking import parse_wb_marking_error, validate_marking_code
from apps.sellers.models import Seller
from apps.warehouse.models import Product
from apps.warehouse.services.marking_lookup import resolve_product_requires_marking


class AssemblyError(Exception):
  def __init__(self, message: str, *, code: str = "error", order: Order | None = None):
    super().__init__(message)
    self.code = code
    self.order = order


def format_sticker_number(order: Order) -> str:
  part_a = (order.sticker_part_a or "").strip()
  part_b = (order.sticker_part_b or "").strip()
  if part_a and part_b:
    return f"{part_a} / {part_b}"
  return part_a or part_b


def _sticker_hint(order: Order) -> str:
  number = format_sticker_number(order)
  if not number:
    return ""
  return f" Номер стикера: {number}."


def _marking_error(message: str, order: Order, *, code: str) -> AssemblyError:
  text = message.rstrip(".")
  hint = _sticker_hint(order)
  if hint and hint.strip() not in text:
    text = f"{text}.{hint}"
  return AssemblyError(text, code=code, order=order)


def _get_client(seller: Seller) -> WBClient:
  if not seller.wb_api_token_encrypted:
    raise AssemblyError(f"У селлера «{seller.company_name}» не задан токен WB")
  try:
    token = decrypt_token(seller.wb_api_token_encrypted)
  except TokenCryptoError as exc:
    raise AssemblyError(str(exc)) from exc
  return WBClient(token)


def _match_order_by_scan(orders_qs, scan_value: str) -> Order | None:
  order = orders_qs.filter(barcode=scan_value).first()
  if not order and scan_value.isdigit():
    order = orders_qs.filter(wb_order_id=int(scan_value)).first()
  return order


def _is_marking_retry_order(order: Order) -> bool:
  return (
    order.status in (Order.Status.LABEL_PRINTED, Order.Status.MARKED)
    and (order.marking_verify_status or "").strip() == "error"
  )


def _reset_marking_for_retry(order: Order, seller: Seller, *, user=None) -> None:
  """После отклонения ЧЗ WB — снова ждём скан DataMatrix по тому же баркоду."""
  if order.marking_code:
    client = _get_client(seller)
    try:
      client.delete_order_meta(order.wb_order_id, key="sgtin")
    except WBApiError as exc:
      raise _marking_error(
        f"Не удалось снять привязку ЧЗ в WB: {parse_wb_marking_error(exc)}",
        order,
        code="wb_unbind_failed",
      ) from exc

  order.marking_code = ""
  order.marking_bound = False
  order.marking_verify_status = ""
  order.marking_verify_error = ""
  order.status = Order.Status.ASSEMBLED
  order.save(
    update_fields=[
      "marking_code",
      "marking_bound",
      "marking_verify_status",
      "marking_verify_error",
      "status",
      "updated_at",
    ],
  )

  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.ASSEMBLY,
    message=(
      f"Повторная привязка ЧЗ после ошибки WB — заказ #{order.wb_order_id}"
      f"{_sticker_hint(order)}"
    ),
    details={"order_id": order.id, "barcode": order.barcode},
  )


def _get_active_pick_list(seller: Seller) -> PickList | None:
  return (
    PickList.objects.filter(seller=seller, is_completed=False)
    .order_by("-created_at")
    .first()
  )


def _scan_allowed_in_pick_list(pick_list: PickList, scan_value: str) -> bool:
  scan = scan_value.strip()
  if not scan:
    return False

  item_barcodes = set(
    PickListItem.objects.filter(pick_list=pick_list).values_list("barcode", flat=True)
  )
  if scan in item_barcodes:
    return True

  if scan.isdigit():
    order = Order.objects.filter(
      seller_id=pick_list.seller_id,
      pick_list=pick_list,
      wb_order_id=int(scan),
    ).first()
    if order and order.barcode in item_barcodes:
      return True

  return False


def _assert_scan_in_pick_list(seller: Seller, scan_value: str) -> None:
  pick_list = _get_active_pick_list(seller)
  if not pick_list or not pick_list.items.exists():
    return
  if not _scan_allowed_in_pick_list(pick_list, scan_value):
    raise AssemblyError("Баркода нет в листе подбора!", code="not_in_pick_list")


def _find_active_order(seller: Seller, scan_value: str) -> Order:
  scan_value = scan_value.strip()
  if not scan_value:
    raise AssemblyError("Пустой штрихкод")

  base_qs = filter_orders_for_seller(
    Order.objects.filter(
      seller=seller,
      assembly_hidden=False,
    ).select_related("product"),
    seller,
  )

  active_qs = base_qs.filter(
    status__in=[Order.Status.IN_PICKING, Order.Status.ASSEMBLED],
  )
  order = _match_order_by_scan(active_qs, scan_value)
  if order:
    return order

  retry_qs = base_qs.filter(
    status__in=[Order.Status.LABEL_PRINTED, Order.Status.MARKED],
    marking_verify_status="error",
  )
  order = _match_order_by_scan(retry_qs, scan_value)
  if order:
    return order

  raise AssemblyError(
    "Заказ не найден в текущей сборке. "
    "Проверьте баркод или обновите заказы из WB.",
    code="order_not_found",
  )


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
  """Передать новые заказы на сборку в WB — одна поставка на склад."""
  from apps.orders.services.supply_flow import (  # noqa: PLC0415
    SupplyFlowError,
    send_orders_to_assembly_bulk,
  )

  try:
    result = send_orders_to_assembly_bulk(seller, user=user)
  except SupplyFlowError as exc:
    raise AssemblyError(str(exc), code=getattr(exc, "code", "error")) from exc

  wb_errors = [
    item.get("error", "")
    for item in result.get("errors", [])
    if item.get("error")
  ]

  return {
    "orders_count": result["total"],
    "wb_assembly_sent": result["sent"],
    "wb_assembly_errors": wb_errors,
    "stickers_fetched": result["stickers_fetched"],
    "sticker_errors": "",
    "supplies": result.get("supplies", 0),
  }


def scan_order_barcode(seller: Seller, scan_value: str, *, user=None) -> dict:
  """
  Шаг 1: скан баркода заказа.
  — без ЧЗ: сразу LABEL_PRINTED + печать;
  — с ЧЗ: ждём скан DataMatrix (стикер не печатаем).
  """
  scan_value = scan_value.strip()
  if not scan_value:
    raise AssemblyError("Пустой штрихкод")

  _assert_scan_in_pick_list(seller, scan_value)
  order = _find_active_order(seller, scan_value)

  if _is_marking_retry_order(order):
    if not _order_requires_marking(order):
      raise AssemblyError(
        "Заказ с ошибкой ЧЗ не требует маркировки — обратитесь к администратору",
        code="marking_retry_invalid",
        order=order,
      )
    _reset_marking_for_retry(order, seller, user=user)

  if not order.has_sticker or not order.sticker_file:
    raise AssemblyError(
      f"Стикер для заказа WB #{order.wb_order_id} ещё не загружен. "
      "Нажмите «Передать на сборку» или обновите заказы.",
      code="no_sticker",
    )

  if not order.product:
    product = Product.objects.filter(seller=seller, barcode=order.barcode).first()
    if product:
      order.product = product
      order.save(update_fields=["product", "updated_at"])

  requires_marking = _order_requires_marking(order)

  if requires_marking:
    wb_status = (order.wb_supplier_status or "").strip()
    if wb_status != WB_SUPPLIER_ASSEMBLY:
      raise AssemblyError(
        f"Заказ WB #{order.wb_order_id} ещё не на сборке в WB "
        f"(статус: {wb_status or 'new'}). "
        "Сначала нажмите «Передать на сборку» на шаге 1.",
        code="wb_not_confirm",
      )

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
) -> dict:
  """Скан ЧЗ → привязка в WB → сразу печать стикера (проверка WB — в фоне)."""
  try:
    order = Order.objects.select_related("product").get(
      pk=order_id,
      seller=seller,
    )
  except Order.DoesNotExist as exc:
    raise AssemblyError("Заказ не найден", code="order_not_found") from exc

  if order.status not in (Order.Status.IN_PICKING, Order.Status.ASSEMBLED):
    raise _marking_error(
      f"Заказ WB #{order.wb_order_id} не ожидает привязку ЧЗ "
      f"(статус: {order.get_status_display()}). Нажмите «Заменить товар» для сброса",
      order,
      code="invalid_status",
    )

  if not _order_requires_marking(order):
    raise AssemblyError(
      "Для этого заказа маркировка ЧЗ не требуется",
      code="marking_not_required",
      order=order,
    )

  wb_status = (order.wb_supplier_status or "").strip()
  if wb_status != WB_SUPPLIER_ASSEMBLY:
    raise _marking_error(
      f"Заказ WB #{order.wb_order_id} не на сборке в WB "
      f"(статус: {wb_status or 'new'}). "
      "WB принимает ЧЗ только для заказов в статусе confirm. "
      "Сначала отправьте заказ на сборку («На сборку» / «Все на сборку»)",
      order,
      code="wb_not_confirm",
    )

  if not order.has_sticker or not order.sticker_file:
    raise _marking_error(
      "Стикер не загружен — начните сборку заново",
      order,
      code="no_sticker",
    )

  normalized, validation_error = validate_marking_code(marking_code)
  if validation_error:
    raise _marking_error(validation_error, order, code="invalid_marking_code")

  duplicate = (
    Order.objects.filter(marking_code=normalized)
    .exclude(pk=order.pk)
    .exclude(marking_verify_status="error")
    .exists()
  )
  if duplicate:
    raise _marking_error(
      "Этот код ЧЗ уже использован для другого заказа в CRM. "
      "Возьмите другой экземпляр товара",
      order,
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
    raise _marking_error(parse_wb_marking_error(exc), order, code="wb_bind_failed") from exc

  order.marking_code = normalized
  order.marking_bound = False
  order.marking_verify_status = "pending"
  order.marking_verify_error = ""
  order.status = Order.Status.LABEL_PRINTED
  order.save(
    update_fields=[
      "marking_code",
      "marking_bound",
      "marking_verify_status",
      "marking_verify_error",
      "status",
      "updated_at",
    ]
  )

  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.MARKING,
    message=f"ЧЗ отправлен в WB — заказ #{order.wb_order_id}, стикер к печати",
    details={"order_id": order.id, "barcode": order.barcode},
  )
  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.LABEL_PRINT,
    message=f"Печать стикера после ЧЗ — заказ WB #{order.wb_order_id}",
    details={"order_id": order.id, "barcode": order.barcode},
  )

  return {
    "action": "print",
    "order": order,
    "message": (
      f"ЧЗ отправлен в WB для заказа #{order.wb_order_id}. "
      "Стикер печатается сразу; проверка в «Честном знаке» займёт несколько минут."
    ),
  }


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
    Order.Status.MARKED,
  ):
    raise AssemblyError(
      f"Заказ WB #{order.wb_order_id} нельзя сбросить "
      f"(статус: {order.get_status_display()})",
      code="invalid_status",
    )

  if order.marking_code:
    client = _get_client(seller)
    try:
      client.delete_order_meta(order.wb_order_id, key="sgtin")
    except WBApiError as exc:
      raise _marking_error(
        f"Не удалось снять привязку ЧЗ в WB: {parse_wb_marking_error(exc)}. "
        "Проверьте заказ в личном кабинете WB",
        order,
        code="wb_unbind_failed",
      ) from exc

  order.marking_code = ""
  order.marking_bound = False
  order.marking_verify_status = ""
  order.marking_verify_error = ""
  order.status = Order.Status.IN_PICKING
  order.save(
    update_fields=[
      "marking_code",
      "marking_bound",
      "marking_verify_status",
      "marking_verify_error",
      "status",
      "updated_at",
    ],
  )

  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.ASSEMBLY,
    message=f"Замена товара: сброс заказа WB #{order.wb_order_id}",
    details={"order_id": order.id, "barcode": order.barcode},
  )

  return order


def _detach_order_from_pick_list(order: Order) -> None:
  pick_list_id = order.pick_list_id
  if not pick_list_id:
    return

  item_qs = PickListItem.objects.filter(pick_list_id=pick_list_id, barcode=order.barcode)
  if order.product_id:
    item_qs = item_qs.filter(product_id=order.product_id)
  item = item_qs.first()

  if item:
    if item.quantity > 1:
      item.quantity -= 1
      item.save(update_fields=["quantity"])
    else:
      item.delete()

  order.pick_list = None

  pick_list = PickList.objects.filter(pk=pick_list_id).first()
  if pick_list and not pick_list.items.exists():
    pick_list.delete()


def remove_order_from_assembly(seller: Seller, order_id: int, *, user=None) -> dict:
  """Скрыть заказ из сборки FBS (на любом этапе вкладок)."""
  from apps.orders.services.supply_flow import get_assembly_stage_counts

  try:
    order = Order.objects.get(pk=order_id, seller=seller)
  except Order.DoesNotExist as exc:
    raise AssemblyError("Заказ не найден", code="order_not_found") from exc

  if order.assembly_hidden:
    raise AssemblyError("Заказ уже удалён из сборки", code="already_hidden")

  if order.marking_code:
    client = _get_client(seller)
    try:
      client.delete_order_meta(order.wb_order_id, key="sgtin")
    except WBApiError as exc:
      raise _marking_error(
        f"Не удалось снять привязку ЧЗ в WB: {parse_wb_marking_error(exc)}. "
        "Проверьте заказ в личном кабинете WB",
        order,
        code="wb_unbind_failed",
      ) from exc

  _detach_order_from_pick_list(order)

  for supply in Supply.objects.filter(seller=seller, status=Supply.Status.FORMING, orders=order):
    supply.orders.remove(order)

  order.assembly_hidden = True
  order.marking_code = ""
  order.marking_bound = False
  order.marking_verify_status = ""
  order.marking_verify_error = ""
  order.save(
    update_fields=[
      "pick_list",
      "assembly_hidden",
      "marking_code",
      "marking_bound",
      "marking_verify_status",
      "marking_verify_error",
      "updated_at",
    ],
  )

  seller_update_fields: list[str] = []
  wb_new_ids = list(seller.wb_new_order_ids or [])
  if order.wb_order_id in wb_new_ids:
    seller.wb_new_order_ids = [wid for wid in wb_new_ids if wid != order.wb_order_id]
    seller.wb_count_new = max(0, (seller.wb_count_new or 0) - 1)
    seller_update_fields.extend(["wb_new_order_ids", "wb_count_new"])

  wb_supplier = (order.wb_supplier_status or "").strip()
  if wb_supplier == WB_SUPPLIER_ASSEMBLY:
    seller.wb_count_assembly = max(0, (seller.wb_count_assembly or 0) - 1)
    seller_update_fields.append("wb_count_assembly")

  if seller_update_fields:
    seller_update_fields.append("updated_at")
    seller.save(update_fields=seller_update_fields)

  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.ASSEMBLY,
    message=f"Удалён из сборки FBS: заказ WB #{order.wb_order_id}",
    details={"order_id": order.id, "barcode": order.barcode},
  )

  counts = get_assembly_stage_counts(seller)
  return {
    "order": order,
    "counts": counts,
    "assembly_eligible": counts["new"],
  }


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
  """Счётчики по БД + фильтр складов (для списков заказов в сборке)."""
  qs = filter_orders_for_seller(Order.objects.filter(seller=seller), seller)
  active = qs.exclude(status=Order.Status.CANCELLED)

  if seller.wb_counts_synced_at:
    in_delivery = seller.wb_count_delivery
  else:
    in_delivery = active.filter(wb_in_delivery_q()).count()

  return {
    "new": active.filter(wb_supplier_status=WB_SUPPLIER_NEW).count(),
    "in_picking": active.filter(wb_supplier_status=WB_SUPPLIER_ASSEMBLY).count(),
    "in_delivery": in_delivery,
    "assembled": active.filter(status=Order.Status.ASSEMBLED).count(),
    "label_printed": active.filter(status=Order.Status.LABEL_PRINTED).count(),
    "marked": active.filter(status=Order.Status.MARKED).count(),
    "in_supply": active.filter(status=Order.Status.IN_SUPPLY).count(),
    "shipped": qs.filter(status=Order.Status.SHIPPED).count(),
    "cancelled": qs.filter(status=Order.Status.CANCELLED).count(),
  }


def get_seller_wb_tab_counts(seller: Seller) -> dict[str, int]:
  """Счётчики вкладок как в ЛК WB — из live API после синка."""
  if seller.wb_counts_synced_at:
    return {
      "new": seller.wb_count_new,
      "in_picking": seller.wb_count_assembly,
      "in_delivery": seller.wb_count_delivery,
    }
  stage = get_seller_stage_counts(seller)
  return {
    "new": stage["new"],
    "in_picking": stage["in_picking"],
    "in_delivery": stage["in_delivery"],
  }


def get_wb_stage_label(wb_supplier_status: str) -> str:
  return WB_SUPPLIER_LABELS.get(wb_supplier_status, wb_supplier_status or "—")
