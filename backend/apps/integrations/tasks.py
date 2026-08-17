"""Celery tasks for Wildberries integration."""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def sync_wb_orders():
  """Sync new orders and statuses from WB API for all active sellers."""
  from apps.orders.services.sync_orders import sync_all_active_sellers

  result = sync_all_active_sellers()
  if result["errors"]:
    logger.warning("WB order sync errors: %s", result["errors"])
  logger.info("WB order sync done: %s", result["results"])


@shared_task
def sync_wb_stocks(seller_id: int):
  """Push stock quantities to WB for a seller."""
  # TODO: implement WB FBS stocks API
  logger.info("WB stock sync queued for seller %s", seller_id)
