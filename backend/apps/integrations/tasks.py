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
  """Ежедневное обновление названий и маркировки товаров из WB Content API."""
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
def clear_expired_marking_codes():
  """Удалить коды ЧЗ из БД через 3 часа после передачи в доставку."""
  from apps.orders.services.marking_cleanup import clear_expired_marking_codes as run_cleanup

  result = run_cleanup()
  if result["wb_cleared"] or result["ozon_cleared"]:
    logger.info("Expired marking codes cleared: %s", result)
  return result
