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

  def _cutoff_window(self) -> tuple[str, str]:
    now = datetime.now(dt_timezone.utc)
    cutoff_from = (now - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
    cutoff_to = (now + timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return cutoff_from, cutoff_to

  def _extract_postings(self, data: dict) -> tuple[list[dict], bool, str]:
    if not isinstance(data, dict):
      return [], False, ""
    result = data.get("result") if isinstance(data.get("result"), dict) else {}
    postings = data.get("postings") or result.get("postings") or []
    has_next = bool(data.get("has_next") if "has_next" in data else result.get("has_next"))
    cursor = str(data.get("cursor") or result.get("cursor") or "")
    return list(postings), has_next, cursor

  def _list_v4(self, status: str | None = None) -> list[dict]:
    """Актуальный список FBS: /v4/posting/fbs/list (курсор, since/to)."""
    now = datetime.now(dt_timezone.utc)
    since = (now - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    until = (now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    collected: list[dict] = []
    cursor = ""
    for _ in range(40):
      payload: dict = {
        "dir": "ASC",
        "filter": {"since": since, "to": until},
        "limit": PAGE_LIMIT,
        "with": {
          "analytics_data": False,
          "financial_data": False,
          "barcodes": True,
        },
      }
      if status:
        payload["filter"]["status"] = status
      if cursor:
        payload["cursor"] = cursor
      data = self._post("/v4/posting/fbs/list", payload)
      if not isinstance(data, dict):
        break
      postings, has_next, next_cursor = self._extract_postings(data)
      collected.extend(postings)
      if not has_next or not postings:
        break
      cursor = next_cursor
      if not cursor:
        break
    return collected

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

  def _unfulfilled_list(self, status: str | None = None) -> list[dict]:
    cutoff_from, cutoff_to = self._cutoff_window()
    offset = 0
    collected: list[dict] = []
    while offset <= 2000:
      data = self._unfulfilled_page(
        status=status,
        offset=offset,
        cutoff_from=cutoff_from,
        cutoff_to=cutoff_to,
      )
      postings, _, _ = self._extract_postings(data)
      if not postings and isinstance(data.get("result"), dict):
        postings = data["result"].get("postings") or []
      collected.extend(postings)
      if len(postings) < PAGE_LIMIT:
        break
      offset += PAGE_LIMIT
    return collected

  def list_postings(self, status: str) -> list[dict]:
    try:
      return self._list_v4(status)
    except OzonApiError as exc:
      logger.warning("Ozon v4 list failed (%s), fallback unfulfilled: %s", status, exc)
      return self._unfulfilled_list(status)

  def posting_status_count(self, status: str, *, max_offset: int = 2000) -> int:
    return len(self.list_postings(status))

  def posting_tab_counts(self) -> dict[str, int]:
    """Новые = awaiting_packaging; в доставке = awaiting_deliver; сборка CRM — локально."""
    new_count = self.posting_status_count("awaiting_packaging")
    delivery_count = self.posting_status_count("awaiting_deliver")
    return {
      "new": new_count,
      "in_picking": 0,
      "in_delivery": delivery_count,
    }

  def ship_posting(self, posting_number: str, packages: list[dict]) -> dict:
    data = self._post("/v4/posting/fbs/ship", {
      "posting_number": posting_number,
      "packages": packages,
    })
    return data if isinstance(data, dict) else {}

  def package_label(self, posting_numbers: list[str]) -> bytes:
    """PDF этикетки отправления. После ship нужно подождать ~1 мин."""
    url = f"{self._base_url}/v2/posting/fbs/package-label"
    try:
      with httpx.Client(timeout=60.0) as client:
        response = client.post(
          url,
          headers=self._headers(),
          json={"posting_number": posting_numbers},
        )
    except httpx.RequestError as exc:
      raise OzonApiError(f"Ошибка сети Ozon API: {exc}") from exc
    if response.status_code >= 400:
      raise OzonApiError(
        f"Ozon API ошибка {response.status_code}: {response.text[:240]}",
        status_code=response.status_code,
      )
    content_type = response.headers.get("content-type", "")
    if "pdf" in content_type or response.content[:4] == b"%PDF":
      return response.content
    try:
      data = response.json()
    except ValueError as exc:
      raise OzonApiError("Ozon не вернул PDF этикетки") from exc
    raise OzonApiError(str((data or {}).get("message") or data)[:240])
