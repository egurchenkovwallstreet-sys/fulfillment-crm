"""Клиент Ozon Seller API (FBS). Заголовки: Client-Id + Api-Key."""
from __future__ import annotations

import base64
import logging
from datetime import datetime, timedelta, timezone as dt_timezone

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

PAGE_LIMIT = 100
REQUEST_TIMEOUT = 30.0


class OzonApiError(Exception):
  def __init__(self, message: str, status_code: int | None = None, code: str = ""):
    super().__init__(message)
    self.status_code = status_code
    self.code = code


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
    warehouses = self.warehouse_list()
    return {"ok": True, "warehouses": len(warehouses)}

  def warehouse_list(self) -> list[dict]:
    last_error: OzonApiError | None = None
    for path in ("/v2/warehouse/list", "/v1/warehouse/list"):
      try:
        data = self._post(path, {})
      except OzonApiError as exc:
        last_error = exc
        if path.endswith("/v2/warehouse/list"):
          logger.warning("Ozon warehouse v2 failed, fallback v1: %s", exc)
          continue
        raise
      result = data.get("result") if isinstance(data, dict) else data
      if isinstance(result, list):
        return result
      if isinstance(result, dict):
        return result.get("warehouses") or result.get("items") or []
    if last_error:
      raise last_error
    return []

  def product_list_ids(self) -> list[dict]:
    """Краткие карточки: product_id + offer_id. POST /v3/product/list."""
    last_id = ""
    collected: list[dict] = []
    for _ in range(80):
      data = self._post("/v3/product/list", {
        "filter": {"visibility": "ALL"},
        "last_id": last_id,
        "limit": PAGE_LIMIT,
      })
      if not isinstance(data, dict):
        break
      result = data.get("result") if isinstance(data.get("result"), dict) else data
      items = result.get("items") or []
      collected.extend(item for item in items if isinstance(item, dict))
      last_id = str(result.get("last_id") or "")
      if not items or not last_id:
        break
    return collected

  def product_info_list(self, product_ids: list[int]) -> list[dict]:
    """Детали карточек. POST /v3/product/info/list, пачки до 100."""
    collected: list[dict] = []
    chunk_size = 100
    for start in range(0, len(product_ids), chunk_size):
      chunk = product_ids[start:start + chunk_size]
      if not chunk:
        continue
      data = self._post("/v3/product/info/list", {
        "product_id": chunk,
        "offer_id": [],
        "sku": [],
      })
      if not isinstance(data, dict):
        continue
      items = data.get("items")
      if items is None and isinstance(data.get("result"), dict):
        items = data["result"].get("items")
      if items is None and isinstance(data.get("result"), list):
        items = data["result"]
      collected.extend(item for item in (items or []) if isinstance(item, dict))
    return collected

  def fbs_stocks_by_offer_ids(self, offer_ids: list[str]) -> list[dict]:
    """Остатки FBS по складам. v2, fallback v1."""
    unique = [item for item in dict.fromkeys(offer_ids) if item]
    collected: list[dict] = []
    chunk_size = 100
    for start in range(0, len(unique), chunk_size):
      collected.extend(self._fbs_stocks_request({
        "limit": 1000,
        "cursor": "",
        "offer_id": unique[start:start + chunk_size],
      }))
    return collected

  def fbs_stocks_by_skus(self, skus: list[str]) -> list[dict]:
    unique = [item for item in dict.fromkeys(str(sku) for sku in skus) if item]
    collected: list[dict] = []
    chunk_size = 100
    for start in range(0, len(unique), chunk_size):
      collected.extend(self._fbs_stocks_request({
        "limit": 1000,
        "cursor": "",
        "sku": unique[start:start + chunk_size],
      }))
    return collected

  def _fbs_stocks_request(self, payload: dict) -> list[dict]:
    last_error: OzonApiError | None = None
    for path in (
      "/v2/product/info/stocks-by-warehouse/fbs",
      "/v1/product/info/stocks-by-warehouse/fbs",
    ):
      try:
        data = self._post(path, payload)
      except OzonApiError as exc:
        last_error = exc
        if "v2" in path:
          logger.warning("Ozon stocks v2 failed, fallback v1: %s", exc)
          continue
        raise
      if not isinstance(data, dict):
        return []
      products = data.get("products")
      if products is None and isinstance(data.get("result"), dict):
        products = data["result"].get("products") or data["result"].get("items")
      if products is None and isinstance(data.get("result"), list):
        products = data["result"]
      return [item for item in (products or []) if isinstance(item, dict)]
    if last_error:
      raise last_error
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

  def list_recent_postings(self, *, days: int = 30) -> list[dict]:
    """Все отправления FBS за период (без фильтра по статусу)."""
    now = datetime.now(dt_timezone.utc)
    since = (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
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

  def _binary_post(self, path: str, payload: dict, *, timeout: float = 60.0) -> bytes:
    url = f"{self._base_url}{path}"
    try:
      with httpx.Client(timeout=timeout) as client:
        response = client.post(url, headers=self._headers(), json=payload)
    except httpx.RequestError as exc:
      raise OzonApiError(f"Ошибка сети Ozon API: {exc}") from exc
    if response.status_code >= 400:
      text = response.text[:240]
      lowered = text.lower()
      code = ""
      if "aren't ready" in lowered or "not ready" in lowered or "не готов" in lowered:
        code = "not_ready"
      raise OzonApiError(
        f"Ozon API ошибка {response.status_code}: {text}",
        status_code=response.status_code,
        code=code,
      )
    content_type = (response.headers.get("content-type") or "").lower()
    body = response.content or b""
    if "pdf" in content_type or body[:4] == b"%PDF":
      return body
    if "image/" in content_type or body[:8] in (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff"):
      return body
    try:
      data = response.json()
    except ValueError as exc:
      if body:
        return body
      raise OzonApiError("Ozon не вернул файл") from exc
    if not isinstance(data, dict):
      raise OzonApiError("Ozon вернул неожиданный ответ")
    message = str(data.get("message") or data.get("error") or "")
    lowered = message.lower()
    if "aren't ready" in lowered or "not ready" in lowered or "не готов" in lowered:
      raise OzonApiError(
        "Документ ещё готовится. Подождите около минуты и нажмите ещё раз.",
        status_code=response.status_code,
        code="not_ready",
      )
    for key in ("file_content", "content", "barcode"):
      raw = data.get(key)
      if isinstance(raw, str) and raw.strip():
        try:
          return base64.b64decode(raw)
        except ValueError:
          continue
    result = data.get("result")
    if isinstance(result, dict):
      for key in ("file_content", "content", "barcode"):
        raw = result.get(key)
        if isinstance(raw, str) and raw.strip():
          try:
            return base64.b64decode(raw)
          except ValueError:
            continue
    raise OzonApiError(message[:240] or str(data)[:240])

  def package_label(self, posting_numbers: list[str]) -> bytes:
    """PDF этикетки отправления. После ship нужно подождать ~1 мин."""
    numbers = [str(item).strip() for item in posting_numbers if str(item).strip()]
    if not numbers:
      raise OzonApiError("Не указаны номера отправлений")
    if len(numbers) > 20:
      raise OzonApiError("Ozon печатает не больше 20 этикеток за раз")
    try:
      return self._binary_post("/v2/posting/fbs/package-label", {"posting_number": numbers})
    except OzonApiError as exc:
      text = str(exc).lower()
      if "aren't ready" in text or "not ready" in text or exc.code == "not_ready":
        raise OzonApiError(
          "Этикетка ещё готовится. Подождите около минуты после «В доставку» и нажмите ещё раз.",
          status_code=exc.status_code,
          code="not_ready",
        ) from exc
      raise

  def carriage_create(self, delivery_method_id: int, *, comment: str = "") -> dict:
    """Создать отгрузку FBS. Пустое тело {} нельзя — Ozon создаст чужую отгрузку."""
    if not delivery_method_id:
      raise OzonApiError("Не указан метод доставки Ozon")
    payload: dict = {"delivery_method_id": int(delivery_method_id)}
    if comment:
      payload["comment"] = comment[:500]
    data = self._post("/v1/carriage/create", payload)
    return data if isinstance(data, dict) else {}

  def carriage_approve(self, carriage_id: int) -> dict:
    data = self._post("/v1/carriage/approve", {"carriage_id": int(carriage_id)})
    return data if isinstance(data, dict) else {}

  def carriage_delivery_list(self, status: str = "new") -> list[dict]:
    data = self._post("/v1/carriage/delivery/list", {"status": status, "limit": 50})
    if not isinstance(data, dict):
      return []
    result = data.get("result")
    if isinstance(result, list):
      return [item for item in result if isinstance(item, dict)]
    if isinstance(result, dict):
      items = result.get("result") or result.get("items") or result.get("deliveries") or []
      return [item for item in items if isinstance(item, dict)]
    return []

  def act_get_barcode(self, carriage_id: int) -> bytes:
    return self._binary_post("/v2/posting/fbs/act/get-barcode", {"id": int(carriage_id)})

  def act_get_pdf(self, carriage_id: int) -> bytes:
    last_error: OzonApiError | None = None
    for path, payload in (
      ("/v2/posting/fbs/digital/act/get-pdf", {"id": int(carriage_id), "doc_type": "act_of_acceptance"}),
      ("/v2/posting/fbs/act/get-pdf", {"id": int(carriage_id)}),
    ):
      try:
        return self._binary_post(path, payload)
      except OzonApiError as exc:
        last_error = exc
        logger.warning("Ozon act PDF %s failed: %s", path, exc)
        continue
    if last_error:
      raise last_error
    raise OzonApiError("Ozon не вернул PDF акта")

  def update_stocks(self, stocks: list[dict]) -> list[dict]:
    """Остатки FBS. POST /v2/products/stocks, пачки до 100."""
    collected: list[dict] = []
    chunk_size = 100
    for start in range(0, len(stocks), chunk_size):
      chunk = stocks[start:start + chunk_size]
      data = self._post("/v2/products/stocks", {"stocks": chunk})
      if not isinstance(data, dict):
        continue
      result = data.get("result")
      items = []
      if isinstance(result, list):
        items = result
      elif isinstance(result, dict):
        items = result.get("stocks") or result.get("items") or []
      collected.extend(item for item in items if isinstance(item, dict))
    return collected
