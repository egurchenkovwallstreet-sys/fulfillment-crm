"""Клиент Statistics API Wildberries — заказы как в сводном отчёте ЛК."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone as dt_timezone
from typing import Iterator

import httpx
from django.conf import settings
from django.utils import timezone

from apps.integrations.wb_client import WBApiError

logger = logging.getLogger(__name__)

REQUEST_INTERVAL_SEC = 61  # лимит WB: 1 запрос в минуту


class WBStatisticsClient:
  def __init__(self, token: str, base_url: str | None = None):
    if not token:
      raise WBApiError("Токен WB не задан")
    self._token = token
    self._base_url = (base_url or settings.WB_STATISTICS_API_BASE_URL).rstrip("/")

  def _headers(self) -> dict[str, str]:
    return {"Authorization": self._token}

  def _request(self, method: str, path: str, **kwargs) -> list | dict:
    url = f"{self._base_url}{path}"
    try:
      with httpx.Client(timeout=60.0) as client:
        response = client.request(method, url, headers=self._headers(), **kwargs)
    except httpx.RequestError as exc:
      raise WBApiError(f"Ошибка сети WB Statistics API: {exc}") from exc

    if response.status_code == 401:
      raise WBApiError("Токен WB недействителен для Statistics API", status_code=401)
    if response.status_code == 429:
      raise WBApiError("Превышен лимит запросов WB Statistics API", status_code=429)
    if response.status_code >= 400:
      raise WBApiError(
        f"WB Statistics API ошибка {response.status_code}: {response.text[:200]}",
        status_code=response.status_code,
      )

    if not response.content:
      return []
    payload = response.json()
    if isinstance(payload, list):
      return payload
    return payload

  def iter_supplier_orders(self, date_from: str, *, flag: int = 0) -> Iterator[dict]:
    """
    GET /api/v1/supplier/orders — постранично по lastChangeDate.
    1 строка = 1 позиция в заказе; уникальный заказ — поле srid.
    """
    cursor = date_from
    page = 0
    while True:
      rows = self._request(
        "GET",
        "/api/v1/supplier/orders",
        params={"dateFrom": cursor, "flag": flag},
      )
      if not isinstance(rows, list) or not rows:
        break
      page += 1
      yield from rows
      cursor = rows[-1].get("lastChangeDate")
      if not cursor:
        break
      if len(rows) < 80_000:
        break
      logger.info("WB Statistics orders: page %s, fetching next from %s", page, cursor)
      time.sleep(REQUEST_INTERVAL_SEC)


def parse_statistics_order_date(value) -> datetime | None:
  if not value:
    return None
  if isinstance(value, datetime):
    parsed = value
  else:
    text = str(value).strip().replace("Z", "+00:00")
    try:
      parsed = datetime.fromisoformat(text)
    except ValueError:
      return None
  if timezone.is_naive(parsed):
    return timezone.make_aware(parsed, dt_timezone.utc)
  return parsed


def is_fbs_statistics_row(row: dict) -> bool:
  warehouse_type = (row.get("warehouseType") or "").strip().lower()
  if "продав" in warehouse_type:
    return True
  if "seller" in warehouse_type:
    return True
  return False
