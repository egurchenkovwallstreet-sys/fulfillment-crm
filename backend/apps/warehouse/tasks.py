"""Фоновые задачи склада (очередь heavy — не блокируют сборку FBS)."""
from __future__ import annotations

import logging

from celery import shared_task
from django.core.cache import cache

logger = logging.getLogger(__name__)

STOCK_IMPORT_LOCK_TTL_SEC = 3600


def stock_import_lock_key(seller_id: int) -> str:
  return f"stock_import:seller:{seller_id}"


@shared_task(bind=True, queue="heavy", max_retries=0)
def apply_stock_import_task(
  self,
  seller_id: int,
  *,
  warehouse_id: int,
  rows: list[dict],
  mode: str = "increment",
  user_id: int | None = None,
) -> dict:
  from apps.accounts.models import User
  from apps.sellers.models import Seller
  from apps.warehouse.services.stock_file_import import StockFileImportError, apply_stock_import

  lock_key = stock_import_lock_key(seller_id)
  seller = Seller.objects.filter(pk=seller_id, is_active=True).first()
  if not seller:
    cache.delete(lock_key)
    return {"ok": False, "detail": "Селлер не найден"}

  user = User.objects.filter(pk=user_id).first() if user_id else None
  try:
    result = apply_stock_import(
      seller,
      warehouse_id=warehouse_id,
      rows=rows,
      mode=mode,
      user=user,
    )
    logger.info(
      "Stock import done seller=%s warehouse=%s ok=%s",
      seller_id,
      warehouse_id,
      result.get("ok"),
    )
    return result
  except StockFileImportError as exc:
    logger.warning("Stock import failed seller=%s: %s", seller_id, exc)
    return {"ok": False, "detail": str(exc)}
  finally:
    cache.delete(lock_key)
