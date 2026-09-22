"""Celery tasks for Wildberries integration."""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(queue="sync")
def sync_orders_for_seller_task(
  seller_id: int,
  *,
  user_id: int | None = None,
  mode: str = "quick",
) -> dict:
  """Синхронизация заказов одного селлера — очередь sync, не web."""
  from apps.accounts.models import User
  from apps.orders.services.sync_orders import sync_orders_for_seller
  from apps.sellers.models import Seller

  seller = Seller.objects.filter(pk=seller_id, is_active=True).first()
  if not seller:
    return {"success": False, "detail": "Селлер не найден"}
  user = User.objects.filter(pk=user_id).first() if user_id else None
  result = sync_orders_for_seller(seller, user=user, mode=mode)
  return {"success": True, **result}


@shared_task(queue="sync")
def sync_wb_orders(quick: bool = True):
  """Sync new orders and statuses from WB API for all active sellers."""
  from apps.orders.services.sync_orders import sync_all_active_sellers

  mode = "quick" if quick else "full"
  result = sync_all_active_sellers(mode=mode)
  if result["errors"]:
    logger.warning("WB order sync errors: %s", result["errors"])
  logger.info("WB order sync done: %s", result["results"])


@shared_task
def sync_wb_stocks(seller_id: int):
  """Push stock quantities to WB for a seller."""
  # TODO: implement WB FBS stocks API
  logger.info("WB stock sync queued for seller %s", seller_id)


@shared_task
def sync_wb_product_cards():
  """Ежедневное обновление карточек товаров (фото, размеры, название) из WB/Ozon."""
  from apps.warehouse.services.wb_product_sync import refresh_all_sellers_products_from_wb

  result = refresh_all_sellers_products_from_wb()
  if result["errors"]:
    logger.warning("WB product cards sync errors: %s", result["errors"])
  logger.info("WB product cards sync done: %s", result["results"])
  return result


@shared_task(queue="sync")
def sync_ozon_orders():
  """Синхронизация отправлений Ozon FBS для всех активных селлеров с ключами."""
  from apps.orders.services.ozon_postings import OzonPostingSyncError, sync_ozon_postings
  from apps.sellers.models import Seller

  sellers = (
    Seller.objects.filter(is_active=True, ozon_enabled=True)
    .exclude(ozon_client_id="")
    .exclude(ozon_api_key_encrypted="")
  )
  results = []
  errors = []
  for seller in sellers:
    try:
      stats = sync_ozon_postings(seller)
      results.append({"seller_id": seller.id, **stats})
    except OzonPostingSyncError as exc:
      errors.append({"seller_id": seller.id, "error": str(exc)})
      logger.warning("Ozon posting sync failed for seller %s: %s", seller.id, exc)
  if errors:
    logger.warning("Ozon order sync errors: %s", errors)
  logger.info("Ozon order sync done: %s sellers", len(results))
  return {"results": results, "errors": errors}


@shared_task
def scan_off_crm_shipments():
  """Ежедневный поиск отгрузок через ЛК WB без стикера CRM."""
  from apps.orders.services.off_crm_shipments import scan_off_crm_shipments_all_sellers

  result = scan_off_crm_shipments_all_sellers()
  if result["errors"]:
    logger.warning("Off-CRM shipment scan errors: %s", result["errors"])
  logger.info("Off-CRM shipment scan done: %s sellers", len(result["results"]))
  return result


@shared_task(
  bind=True,
  queue="sync",
  max_retries=5,
  default_retry_delay=30,
)
def fetch_assembly_stickers_task(
  self,
  seller_id: int,
  order_ids: list[int],
  *,
  user_id: int | None = None,
) -> dict:
  """Подтянуть стикеры WB после передачи на сборку — не блокирует кнопку."""
  from django.db.models import Q

  from apps.accounts.models import User
  from apps.orders.models import Order
  from apps.orders.services.assembly import AssemblyError, fetch_stickers_for_orders
  from apps.sellers.models import Seller

  seller = Seller.objects.filter(pk=seller_id, is_active=True).first()
  if not seller or not order_ids:
    return {"success": False, "detail": "Селлер или заказы не найдены"}

  orders = list(
    Order.objects.filter(
      seller=seller,
      pk__in=order_ids,
      assembly_hidden=False,
    ).filter(
      Q(sticker_file="")
      | Q(sticker_file__isnull=True)
      | Q(has_sticker=False),
    ),
  )
  if not orders:
    return {"success": True, "fetched": 0, "skipped": len(order_ids)}

  user = User.objects.filter(pk=user_id).first() if user_id else None
  try:
    fetched = fetch_stickers_for_orders(seller, orders, user=user)
  except AssemblyError as exc:
    status_code = getattr(getattr(exc, "__cause__", None), "status_code", None)
    if status_code == 429 or "лимит" in str(exc).lower():
      logger.warning(
        "WB sticker fetch rate limit seller=%s, retry task",
        seller_id,
      )
      raise self.retry(exc=exc) from exc
    logger.warning("WB sticker fetch failed seller=%s: %s", seller_id, exc)
    return {"success": False, "detail": str(exc)}

  for order in orders:
    order.refresh_from_db(fields=["sticker_file", "has_sticker"])

  still_missing = [
    order for order in orders
    if not (order.sticker_file or "").strip() or not order.has_sticker
  ]
  if still_missing and self.request.retries < 8:
    countdown = min(30, 2 + self.request.retries * 3)
    logger.info(
      "WB stickers partial seller=%s fetched=%s still_missing=%s retry_in=%ss",
      seller_id,
      fetched,
      len(still_missing),
      countdown,
    )
    raise self.retry(countdown=countdown)

  logger.info(
    "WB assembly stickers fetched seller=%s count=%s/%s",
    seller_id,
    fetched,
    len(orders),
  )
  return {
    "success": True,
    "fetched": fetched,
    "requested": len(orders),
    "still_missing": len(still_missing),
  }


@shared_task(queue="sync")
def sync_wb_delivery_scans():
  """Каждые 2 мин — подтянуть scanDt поставок для всех селлеров WB."""
  from apps.orders.services.sync_orders import sync_all_delivery_scans

  result = sync_all_delivery_scans()
  if result["errors"]:
    logger.warning("WB delivery scan sync errors: %s", result["errors"])
  logger.info(
    "WB delivery scan sync done: scanned=%s closed=%s",
    result["totals"].get("supplies_scanned"),
    result["totals"].get("orders_closed"),
  )
  return result


@shared_task
def reconcile_stuck_delivery_orders():
  """Ежедневно в 4:00 — закрыть «зависшие» во «В доставке» после scanDt на WB."""
  from apps.orders.services.supply_sync import reconcile_stuck_in_delivery_all_sellers

  result = reconcile_stuck_in_delivery_all_sellers()
  if result["errors"]:
    logger.warning("Stuck delivery reconcile errors: %s", result["errors"])
  logger.info(
    "Stuck delivery reconcile done: stuck=%s closed=%s",
    result["totals"].get("stuck_supplies"),
    result["totals"].get("orders_closed"),
  )
  return result


@shared_task(queue="sync")
def bind_order_marking_wb_task(order_id: int, marking_code: str, user_id: int | None = None):
  """Привязка ЧЗ в WB после моментальной печати стикера в CRM."""
  from apps.accounts.models import User
  from apps.integrations.models import AuditLog
  from apps.integrations.wb_client import WBApiError
  from apps.orders.models import Order
  from apps.orders.services.assembly import _get_client
  from apps.orders.services.assembly_queue import queue_last_pick_list_marking_verify
  from apps.orders.services.marking import parse_wb_marking_error

  order = (
    Order.objects.filter(pk=order_id)
    .select_related("seller")
    .first()
  )
  if not order:
    return {"success": False, "detail": "order_not_found", "order_id": order_id}

  user = User.objects.filter(pk=user_id).first() if user_id else None
  seller = order.seller
  code = (marking_code or "").strip()
  if not code:
    return {"success": False, "detail": "empty_code", "order_id": order_id}

  client = _get_client(seller)
  try:
    client.bind_order_sgtin(order.wb_order_id, [code])
  except WBApiError as exc:
    error_text = parse_wb_marking_error(exc)
    order.marking_verify_status = "error"
    order.marking_verify_error = error_text
    order.marking_bound = False
    order.save(
      update_fields=[
        "marking_verify_status",
        "marking_verify_error",
        "marking_bound",
        "updated_at",
      ]
    )
    AuditLog.objects.create(
      user=user,
      seller=seller,
      action_type=AuditLog.ActionType.API_ERROR,
      message=f"Ошибка привязки ЧЗ WB #{order.wb_order_id}: {exc}",
      details={"order_id": order.id, "status_code": exc.status_code},
    )
    logger.warning(
      "Background WB marking bind failed order=%s wb=%s: %s",
      order.id,
      order.wb_order_id,
      error_text,
    )
    return {"success": False, "order_id": order.id, "error": error_text}

  queue_last_pick_list_marking_verify(seller)
  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.MARKING,
    message=f"ЧЗ привязан в WB (фон) — заказ #{order.wb_order_id}",
    details={"order_id": order.id, "barcode": order.barcode},
  )
  logger.info("Background WB marking bind ok order=%s wb=%s", order.id, order.wb_order_id)
  return {"success": True, "order_id": order.id}


@shared_task
def verify_seller_marking_codes(seller_id: int):
  """Опросить WB по pending ЧЗ одного селлера (после последнего скана листа)."""
  from apps.orders.services.assembly import AssemblyError
  from apps.orders.services.marking_verification import verify_marking_orders
  from apps.sellers.models import Seller

  seller = Seller.objects.filter(pk=seller_id, is_active=True).first()
  if not seller:
    return {"skipped": True, "seller_id": seller_id}
  try:
    results = verify_marking_orders(seller, force_recheck=True)
  except AssemblyError as exc:
    logger.warning("Marking verify failed for seller %s: %s", seller_id, exc)
    return {"seller_id": seller_id, "error": str(exc)}
  logger.info("Marking verify seller %s: %s orders", seller_id, len(results))
  return {"seller_id": seller_id, "count": len(results)}


@shared_task
def verify_pending_marking_codes():
  """Раз в 10 минут: проверка ЧЗ у всех селлеров с заказами pending."""
  from apps.orders.models import Order

  seller_ids = list(
    Order.objects.filter(marking_verify_status="pending")
    .exclude(marking_code="")
    .values_list("seller_id", flat=True)
    .distinct()
  )
  for seller_id in seller_ids:
    verify_seller_marking_codes.delay(seller_id)
  logger.info("Queued marking verify for %s sellers", len(seller_ids))
  return {"sellers": len(seller_ids)}


@shared_task
def clear_daily_marking_codes():
  """Ежедневно в 23:59 — удалить ЧЗ у отгруженных заказов (CRM «забывает» коды)."""
  from apps.orders.services.marking_cleanup import clear_daily_shipped_marking_codes

  result = clear_daily_shipped_marking_codes()
  if result["wb_cleared"] or result["ozon_cleared"]:
    logger.info("Daily shipped marking codes cleared: %s", result)
  return result


@shared_task
def clear_expired_marking_codes():
  """@deprecated — используйте clear_daily_marking_codes."""
  return clear_daily_marking_codes()


@shared_task
def accrue_daily_storage_charges():
  """Ежедневное начисление хранения по литражу (система 2)."""
  from apps.sellers.services.liter_billing import accrue_daily_storage_all_sellers

  result = accrue_daily_storage_all_sellers()
  logger.info("Daily liter storage accrual: %s", result)
  return result


@shared_task(queue="heavy")
def refresh_admin_billing_cache(fulfillment_id: int | None, marketplace: str = "wb"):
  """Пересчитать кеш статистики отгрузок для кабинета владельца."""
  from apps.sellers.services.admin_billing_cache import rebuild_admin_billing_cache

  result = rebuild_admin_billing_cache(
    fulfillment_id=fulfillment_id,
    marketplace=marketplace,
  )
  logger.info("Admin billing cache refresh: %s", result)
  return result


@shared_task
def rebuild_supply_report_snapshots():
  """Ежедневно ночью — снимок отчёта по поставкам за текущий и прошлый месяц."""
  from apps.sellers.services.supply_report_cache import rebuild_all_supply_report_snapshots

  result = rebuild_all_supply_report_snapshots()
  logger.info(
    "Supply report snapshots rebuilt: fulfillments=%s deleted=%s",
    result["fulfillments"],
    result["deleted_snapshots"],
  )
  return result


@shared_task(queue="heavy")
def refresh_all_admin_billing_caches():
  """Пересчитать кеш статистики для всех фулфилментов и маркетплейсов."""
  from apps.accounts.models import Fulfillment
  from apps.sellers.services.admin_billing_cache import rebuild_admin_billing_cache

  results = []
  for fulfillment in Fulfillment.objects.all().order_by("id"):
    for marketplace in ("wb", "ozon"):
      results.append(
        rebuild_admin_billing_cache(
          fulfillment_id=fulfillment.id,
          marketplace=marketplace,
        )
      )
  logger.info("Admin billing cache refresh all: %s jobs", len(results))
  return {"jobs": len(results), "results": results}


@shared_task(queue="sync", bind=True, max_retries=2, default_retry_delay=30)
def prefetch_seller_shipping_points_task(
  self,
  seller_id: int,
  wb_supply_id: str = "",
  force_refresh: bool = False,
):
  """Фоновая подгрузка СЦ/ППТ WB — отдельно для каждого селлера."""
  from django.core.cache import cache

  from apps.orders.services.supply_flow import (
    _shipping_prefetch_lock_key,
    prefetch_seller_shipping_points_sync,
  )

  supply_key = (wb_supply_id or "").strip() or None
  lock_key = _shipping_prefetch_lock_key(seller_id, supply_key)
  try:
    result = prefetch_seller_shipping_points_sync(
      seller_id,
      wb_supply_id=supply_key,
      force_refresh=force_refresh,
    )
    if not result.get("success"):
      logger.info("Shipping points prefetch skipped seller=%s: %s", seller_id, result)
    else:
      logger.info(
        "Shipping points prefetch seller=%s supply=%s sc=%s pp=%s cargo=%s",
        seller_id,
        supply_key or "-",
        result.get("sc_count"),
        result.get("pp_count"),
        result.get("cargo_type"),
      )
    return result
  except Exception as exc:
    logger.warning("Shipping points prefetch failed seller=%s: %s", seller_id, exc)
    raise self.retry(exc=exc) from exc
  finally:
    if supply_key:
      cache.delete(lock_key)
