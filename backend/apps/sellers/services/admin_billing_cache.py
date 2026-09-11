"""Кеш статистики отгрузок для кабинета владельца (Redis + Celery)."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from django.core.cache import cache
from django.utils import timezone

from apps.sellers.serializers import AdminBillingDashboardSerializer
from apps.sellers.services.seller_billing_stats import load_admin_billing_dashboard

logger = logging.getLogger(__name__)

CACHE_PREFIX = "admin_billing_v1"
CACHE_TTL_SEC = 900
REFRESH_LOCK_TTL_SEC = 600
STALE_AFTER_SEC = 600


def _fulfillment_cache_part(fulfillment_id: int | None) -> str:
  return f"ff_{fulfillment_id}" if fulfillment_id else "all"


def billing_cache_key(*, fulfillment_id: int | None, marketplace: str) -> str:
  return f"{CACHE_PREFIX}:{_fulfillment_cache_part(fulfillment_id)}:{marketplace}"


def billing_lock_key(*, fulfillment_id: int | None, marketplace: str) -> str:
  return f"{billing_cache_key(fulfillment_id=fulfillment_id, marketplace=marketplace)}:lock"


def _serialize_payload(payload: dict) -> dict:
  return AdminBillingDashboardSerializer(payload).data


def get_cached_admin_billing(
  *,
  fulfillment_id: int | None,
  marketplace: str,
) -> tuple[dict | None, dict | None]:
  cached = cache.get(billing_cache_key(fulfillment_id=fulfillment_id, marketplace=marketplace))
  if not isinstance(cached, dict):
    return None, None
  data = cached.get("data")
  meta = cached.get("meta")
  if not isinstance(data, dict) or not isinstance(meta, dict):
    return None, None
  return data, meta


def _cache_age_sec(meta: dict | None) -> float | None:
  if not meta:
    return None
  cached_at = meta.get("cached_at")
  if not cached_at:
    return None
  try:
    parsed = datetime.fromisoformat(str(cached_at))
  except (TypeError, ValueError):
    return None
  if timezone.is_naive(parsed):
    parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
  return (timezone.now() - parsed).total_seconds()


def is_cache_stale(meta: dict | None) -> bool:
  age = _cache_age_sec(meta)
  if age is None:
    return True
  return age >= STALE_AFTER_SEC


def rebuild_admin_billing_cache(
  *,
  fulfillment_id: int | None,
  marketplace: str,
) -> dict[str, Any]:
  """Пересчитать статистику и положить в Redis."""
  from apps.accounts.models import Fulfillment

  lock_key = billing_lock_key(fulfillment_id=fulfillment_id, marketplace=marketplace)
  if not cache.add(lock_key, "1", timeout=REFRESH_LOCK_TTL_SEC):
    logger.info(
      "Admin billing refresh already running: fulfillment=%s marketplace=%s",
      fulfillment_id,
      marketplace,
    )
    return {"skipped": True, "fulfillment_id": fulfillment_id, "marketplace": marketplace}

  fulfillment = None
  if fulfillment_id is not None:
    fulfillment = Fulfillment.objects.filter(pk=fulfillment_id).first()

  try:
    payload = load_admin_billing_dashboard(
      fulfillment=fulfillment,
      marketplace=marketplace,
      parallel=True,
    )
    data = _serialize_payload(payload)
    meta = {
      "cached_at": timezone.now().isoformat(),
      "marketplace": marketplace,
      "fulfillment_id": fulfillment_id,
    }
    cache.set(
      billing_cache_key(fulfillment_id=fulfillment_id, marketplace=marketplace),
      {"data": data, "meta": meta},
      timeout=CACHE_TTL_SEC,
    )
    logger.info(
      "Admin billing cache rebuilt: fulfillment=%s marketplace=%s sellers=%s",
      fulfillment_id,
      marketplace,
      len(data.get("sellers") or []),
    )
    return {"ok": True, **meta, "sellers": len(data.get("sellers") or [])}
  finally:
    cache.delete(lock_key)


def queue_admin_billing_refresh(
  *,
  fulfillment_id: int | None,
  marketplace: str,
) -> bool:
  """Поставить пересчёт в Celery, если ещё не идёт."""
  lock_key = billing_lock_key(fulfillment_id=fulfillment_id, marketplace=marketplace)
  if cache.get(lock_key):
    return False
  from apps.integrations.tasks import refresh_admin_billing_cache

  refresh_admin_billing_cache.delay(fulfillment_id, marketplace)
  return True
