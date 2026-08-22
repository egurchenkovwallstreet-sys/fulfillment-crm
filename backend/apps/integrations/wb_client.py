"""Клиент API Wildberries FBS (marketplace-api)."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

PAGE_LIMIT = 1000
REQUEST_INTERVAL_SEC = 0.1


class WBApiError(Exception):
  def __init__(self, message: str, status_code: int | None = None):
    super().__init__(message)
    self.status_code = status_code


@dataclass
class WBOrderData:
  wb_order_id: int
  barcode: str
  warehouse_id: int | None = None


@dataclass
class WBWarehouseData:
  wb_warehouse_id: int
  name: str = ""
  address: str = ""
  office_id: int | None = None


@dataclass
class WBFetchResult:
  orders: list[WBOrderData] = field(default_factory=list)
  pages: int = 0
  raw_total: int = 0
  skipped_no_barcode: int = 0


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
    if response.status_code == 429:
      raise WBApiError("Превышен лимит запросов WB API", status_code=429)
    if response.status_code >= 400:
      raise WBApiError(
        f"WB API ошибка {response.status_code}: {response.text[:200]}",
        status_code=response.status_code,
      )

    if not response.content:
      return {}
    return response.json()

  def fetch_new_orders(self) -> WBFetchResult:
    """GET /api/v3/orders/new — все новые сборочные задания FBS (с пагинацией)."""
    result = WBFetchResult()
    next_cursor = 0
    seen_ids: set[int] = set()

    while True:
      payload = self._request(
        "GET",
        "/api/v3/orders/new",
        params={"limit": PAGE_LIMIT, "next": next_cursor},
      )
      if not isinstance(payload, dict):
        break

      orders = payload.get("orders") or []
      result.pages += 1
      result.raw_total += len(orders)

      for item in orders:
        wb_id = item.get("id")
        if wb_id is None:
          continue
        wb_id = int(wb_id)
        if wb_id in seen_ids:
          continue
        seen_ids.add(wb_id)

        barcode = _extract_barcode(item)
        if not barcode:
          result.skipped_no_barcode += 1
          logger.warning("WB order %s without barcode, skipped", wb_id)
          continue
        result.orders.append(
          WBOrderData(
            wb_order_id=wb_id,
            barcode=barcode,
            warehouse_id=_extract_warehouse_id(item),
          )
        )

      next_val = payload.get("next", 0) or 0
      try:
        next_cursor = int(next_val)
      except (TypeError, ValueError):
        next_cursor = 0

      if not orders or next_cursor == 0:
        break

      time.sleep(REQUEST_INTERVAL_SEC)

    return result

  def fetch_order_stickers(
    self,
    order_ids: list[int],
    *,
    sticker_type: str = "png",
    width: int = 58,
    height: int = 40,
  ) -> list[dict]:
    """POST /api/v3/orders/stickers — стикеры сборочных заданий."""
    if not order_ids:
      return []

    stickers: list[dict] = []
    batch_size = 100

    for i in range(0, len(order_ids), batch_size):
      batch = order_ids[i : i + batch_size]
      payload = self._request(
        "POST",
        "/api/v3/orders/stickers",
        params={"type": sticker_type, "width": width, "height": height},
        json={"orders": batch},
      )
      if isinstance(payload, dict):
        stickers.extend(payload.get("stickers") or [])
      time.sleep(REQUEST_INTERVAL_SEC)

    return stickers

  def fetch_order_statuses(self, order_ids: list[int]) -> list[dict]:
    """POST /api/v3/orders/status — статусы сборочных заданий."""
    if not order_ids:
      return []

    statuses: list[dict] = []
    batch_size = 100

    for i in range(0, len(order_ids), batch_size):
      batch = order_ids[i : i + batch_size]
      payload = self._request(
        "POST",
        "/api/v3/orders/status",
        json={"orders": batch},
      )
      if isinstance(payload, dict):
        statuses.extend(payload.get("orders") or [])
      time.sleep(REQUEST_INTERVAL_SEC)

    return statuses

  def fetch_recent_order_ids(self, days: int = 30) -> set[int]:
    """GET /api/v3/orders — ID заказов за последние N дней (как в ЛК WB)."""
    return {order.wb_order_id for order in self.fetch_recent_orders(days=days).orders}

  def fetch_recent_orders(self, days: int = 30) -> WBFetchResult:
    """GET /api/v3/orders — архив заказов (макс. 30 дней за запрос по документации WB)."""
    result = WBFetchResult()
    date_from = int(time.time()) - days * 24 * 3600
    next_cursor = 0
    seen_ids: set[int] = set()

    while True:
      payload = self._request(
        "GET",
        "/api/v3/orders",
        params={"limit": PAGE_LIMIT, "next": next_cursor, "dateFrom": date_from},
      )
      if not isinstance(payload, dict):
        break

      orders = payload.get("orders") or []
      result.pages += 1
      result.raw_total += len(orders)

      for item in orders:
        wb_id = item.get("id")
        if wb_id is None:
          continue
        wb_id = int(wb_id)
        if wb_id in seen_ids:
          continue
        seen_ids.add(wb_id)

        barcode = _extract_barcode(item)
        if not barcode:
          result.skipped_no_barcode += 1
          continue
        result.orders.append(
          WBOrderData(
            wb_order_id=wb_id,
            barcode=barcode,
            warehouse_id=_extract_warehouse_id(item),
          )
        )

      next_val = payload.get("next", 0) or 0
      try:
        next_cursor = int(next_val)
      except (TypeError, ValueError):
        next_cursor = 0

      if not orders or next_cursor == 0:
        break

      time.sleep(REQUEST_INTERVAL_SEC)

    return result

  def fetch_supplies(self) -> list[dict]:
    """GET /api/v3/supplies — список поставок FBS."""
    supplies: list[dict] = []
    next_cursor = 0

    while True:
      payload = self._request(
        "GET",
        "/api/v3/supplies",
        params={"limit": PAGE_LIMIT, "next": next_cursor},
      )
      if not isinstance(payload, dict):
        break

      batch = payload.get("supplies") or []
      supplies.extend(batch)

      next_val = payload.get("next", 0) or 0
      try:
        next_cursor = int(next_val)
      except (TypeError, ValueError):
        next_cursor = 0

      if not batch or next_cursor == 0:
        break

      time.sleep(REQUEST_INTERVAL_SEC)

    return supplies

  def fetch_supply_order_ids(self, supply_id: str) -> list[int]:
    """GET /api/marketplace/v3/supplies/{id}/order-ids — ID заказов в поставке."""
    payload = self._request(
      "GET",
      f"/api/marketplace/v3/supplies/{supply_id}/order-ids",
    )
    if not isinstance(payload, dict):
      return []
    ids: list[int] = []
    for raw_id in payload.get("orderIds") or []:
      try:
        ids.append(int(raw_id))
      except (TypeError, ValueError):
        continue
    return ids

  def fetch_delivery_order_ids(self) -> set[int]:
    """ID заказов из поставок, переданных в доставку (done=true)."""
    order_ids: set[int] = set()
    for supply in self.fetch_supplies():
      if not supply.get("done"):
        continue
      supply_id = supply.get("id")
      if not supply_id:
        continue
      order_ids.update(self.fetch_supply_order_ids(str(supply_id)))
      time.sleep(REQUEST_INTERVAL_SEC)
    return order_ids

  def fetch_seller_warehouses(self) -> list[dict]:
    """GET /api/v3/warehouses — склады продавца FBS."""
    payload = self._request("GET", "/api/v3/warehouses")
    if isinstance(payload, list):
      return payload
    if isinstance(payload, dict):
      return payload.get("warehouses") or payload.get("data") or []
    return []

  def bind_order_sgtin(self, order_id: int, sgtins: list[str]) -> None:
    """PUT /api/v3/orders/{orderId}/meta/sgtin — привязка кода ЧЗ к сборочному заданию."""
    if not sgtins:
      raise WBApiError("Не передан код ЧЗ")
    self._request(
      "PUT",
      f"/api/v3/orders/{order_id}/meta/sgtin",
      json={"sgtins": sgtins},
    )

  def delete_order_meta(self, order_id: int, *, key: str = "sgtin") -> None:
    """DELETE /api/v3/orders/{orderId}/meta — удаление метаданных заказа."""
    self._request(
      "DELETE",
      f"/api/v3/orders/{order_id}/meta",
      params={"key": key},
    )

  def create_supply(self, name: str) -> str:
    """POST /api/v3/supplies — создать поставку FBS."""
    payload = self._request("POST", "/api/v3/supplies", json={"name": name})
    if isinstance(payload, dict):
      supply_id = payload.get("id")
      if supply_id is not None:
        return str(supply_id)
    raise WBApiError("Не удалось создать поставку WB")

  def add_orders_to_supply(self, supply_id: str, order_ids: list[int]) -> None:
    """PATCH /api/marketplace/v3/supplies/{supplyId}/orders — добавить заказы в поставку."""
    if not order_ids:
      raise WBApiError("Не переданы ID заказов")
    self._request(
      "PATCH",
      f"/api/marketplace/v3/supplies/{supply_id}/orders",
      json={"orders": order_ids},
    )

  def deliver_supply(self, supply_id: str) -> None:
    """PATCH /api/v3/supplies/{supplyId}/deliver — передать поставку в доставку."""
    self._request("PATCH", f"/api/v3/supplies/{supply_id}/deliver")

  def fetch_supply_barcode(self, supply_id: str, *, barcode_type: str = "png") -> dict:
    """GET /api/v3/supplies/{supplyId}/barcode — QR-код поставки."""
    payload = self._request(
      "GET",
      f"/api/v3/supplies/{supply_id}/barcode",
      params={"type": barcode_type},
    )
    return payload if isinstance(payload, dict) else {}


def _extract_barcode(order_item: dict) -> str:
  skus = order_item.get("skus") or []
  if skus:
    return str(skus[0]).strip()
  article = order_item.get("article")
  if article:
    return str(article).strip()
  return ""


def _extract_warehouse_id(order_item: dict) -> int | None:
  wh_id = order_item.get("warehouseId")
  if wh_id is None:
    return None
  try:
    return int(wh_id)
  except (TypeError, ValueError):
    return None
