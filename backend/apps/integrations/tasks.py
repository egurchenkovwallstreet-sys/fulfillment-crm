"""Celery tasks for Wildberries integration."""
from celery import shared_task


@shared_task
def sync_wb_orders():
  """Sync new orders and statuses from WB API for all active sellers."""
  # TODO: implement WB FBS API integration
  pass


@shared_task
def sync_wb_stocks(seller_id: int):
  """Push stock quantities to WB for a seller."""
  # TODO: implement WB FBS stocks API
  import logging
  logging.getLogger(__name__).info("WB stock sync queued for seller %s", seller_id)
