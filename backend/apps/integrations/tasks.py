"""Celery tasks for Wildberries integration."""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
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


@shared_task
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
    results = verify_marking_orders(seller)
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


@shared_task
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
