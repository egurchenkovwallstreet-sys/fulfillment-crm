"""Клиент Ozon Seller API (FBS). Заголовки: Client-Id + Api-Key."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone as dt_timezone

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

PAGE_LIMIT = 100
REQUEST_TIMEOUT = 30.0


class OzonApiError(Exception):
  def __init__(self, message: str, status_code: int | None = None):
    super().__init__(message)
    self.status_code = status_code


class OzonClient:
  def __init__(self, client_id: str, api_key: str, base_url: str | None = None):
    if not (client_id or "").strip():
      raise OzonApiError("Client-Id Ozon не задан")
    if not (api_key or "").strip():
      raise OzonApiError("Api-Key Ozon не задан")
    self._client_id = client_id.strip()
    self._api_key = api_key.strip()
    self._base_url = (base_url or settings.OZON_API_BASE_URL).rstrip("/")

  def _headers(self) -> dict[str, str]:
    return {
      "Client-Id": self._client_id,
      "Api-Key": self._api_key,
      "Content-Type": "application/json",
    }

  def _request(self, method: str, path: str, **kwargs) -> dict | list:
    url = f"{self._base_url}{path}"
    try:
      with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
        response = client.request(method, url, headers=self._headers(), **kwargs)
    except httpx.RequestError as exc:
      raise OzonApiError(f"Ошибка сети Ozon API: {exc}") from exc

    if response.status_code == 401:
      raise OzonApiError("Ключи Ozon недействительны", status_code=401)
    if response.status_code == 403:
      raise OzonApiError("Нет доступа к Ozon API (проверьте права ключа)", status_code=403)
    if response.status_code == 429:
      raise OzonApiError("Превышен лимит запросов Ozon API", status_code=429)
    if response.status_code >= 400:
      raise OzonApiError(
        f"Ozon API ошибка {response.status_code}: {response.text[:240]}",
        status_code=response.status_code,
      )

    if not response.content:
      return {}
    try:
      return response.json()
    except ValueError as exc:
      raise OzonApiError("Ozon API вернул не JSON") from exc

  def _post(self, path: str, payload: dict) -> dict | list:
    data = self._request("POST", path, json=payload)
    return data if isinstance(data, (dict, list)) else {}

  def ping(self) -> dict:
    """Проверка ключей: список складов."""
    data = self._post("/v1/warehouse/list", {})
    result = data.get("result") if isinstance(data, dict) else data
    warehouses = []
    if isinstance(result, list):
      warehouses = result
    elif isinstance(result, dict):
      warehouses = result.get("warehouses") or result.get("items") or []
    return {"ok": True, "warehouses": len(warehouses)}

  def warehouse_list(self) -> list[dict]:
    data = self._post("/v1/warehouse/list", {})
    result = data.get("result") if isinstance(data, dict) else data
    if isinstance(result, list):
      return result
    if isinstance(result, dict):
      return result.get("warehouses") or result.get("items") or []
    return []

  def _unfulfilled_page(self, *, status: str | None, offset: int, cutoff_from: str, cutoff_to: str) -> dict:
    payload: dict = {
      "dir": "ASC",
      "filter": {
        "cutoff_from": cutoff_from,
        "cutoff_to": cutoff_to,
      },
      "limit": PAGE_LIMIT,
      "offset": offset,
      "with": {"analytics_data": False, "financial_data": False},
    }
    if status:
      payload["filter"]["status"] = status
    data = self._post("/v4/posting/fbs/unfulfilled/list", payload)
    return data if isinstance(data, dict) else {}

  def posting_status_count(self, status: str, *, max_offset: int = 2000) -> int:
    now = datetime.now(dt_timezone.utc)
    cutoff_from = (now - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
    cutoff_to = (now + timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%SZ")
    offset = 0
    total = 0
    while offset <= max_offset:
      data = self._unfulfilled_page(
        status=status,
        offset=offset,
        cutoff_from=cutoff_from,
        cutoff_to=cutoff_to,
      )
      result = data.get("result") or {}
      postings = result.get("postings") or []
      total += len(postings)
      if len(postings) < PAGE_LIMIT:
        break
      offset += PAGE_LIMIT
    return total

  def posting_tab_counts(self) -> dict[str, int]:
    """Новые = awaiting_packaging; в доставке = awaiting_deliver; сборка CRM — локально."""
    new_count = self.posting_status_count("awaiting_packaging")
    delivery_count = self.posting_status_count("awaiting_deliver")
    return {
      "new": new_count,
      "in_picking": 0,
      "in_delivery": delivery_count,
    }
