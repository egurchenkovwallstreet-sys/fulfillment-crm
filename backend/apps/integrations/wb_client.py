"""Клиент API Wildberries FBS (marketplace-api)."""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)


class WBApiError(Exception):
  def __init__(self, message: str, status_code: int | None = None):
    super().__init__(message)
    self.status_code = status_code


@dataclass
class WBOrderData:
  wb_order_id: int
  barcode: str


class WBClient:
  def __init__(self, token: str, base_url: str | None = None):
    if not token:
      raise WBApiError("Токен WB не задан")
    self._token = token
    self._base_url = (base_url or settings.WB_API_BASE_URL).rstrip("/")

  def _headers(self) -> dict[str, str]:
    return {"Authorization": self._token}

  def _request(self, method: str, path: str, **kwargs) -> dict | list:
    url = f"{self._base_url}{path}"
    try:
      with httpx.Client(timeout=30.0) as client:
        response = client.request(method, url, headers=self._headers(), **kwargs)
    except httpx.RequestError as exc:
      raise WBApiError(f"Ошибка сети WB API: {exc}") from exc

    if response.status_code == 401:
      raise WBApiError("Токен WB недействителен", status_code=401)
    if response.status_code >= 400:
      raise WBApiError(
        f"WB API ошибка {response.status_code}: {response.text[:200]}",
        status_code=response.status_code,
      )

    if not response.content:
      return {}
    return response.json()

  def fetch_new_orders(self) -> list[WBOrderData]:
    """GET /api/v3/orders/new — новые сборочные задания FBS."""
    payload = self._request("GET", "/api/v3/orders/new")
    orders = payload.get("orders", []) if isinstance(payload, dict) else []
    result: list[WBOrderData] = []

    for item in orders:
      wb_id = item.get("id")
      if wb_id is None:
        continue
      barcode = _extract_barcode(item)
      if not barcode:
        logger.warning("WB order %s without barcode, skipped", wb_id)
        continue
      result.append(WBOrderData(wb_order_id=int(wb_id), barcode=barcode))

    return result


def _extract_barcode(order_item: dict) -> str:
  skus = order_item.get("skus") or []
  if skus:
    return str(skus[0]).strip()
  article = order_item.get("article")
  if article:
    return str(article).strip()
  return ""
