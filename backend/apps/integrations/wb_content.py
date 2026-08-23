"""Клиент Content API Wildberries — карточки товаров, needKiz."""
from __future__ import annotations

import time
from dataclasses import dataclass

from django.conf import settings

from apps.integrations.wb_client import WBApiError, WBClient, REQUEST_INTERVAL_SEC


@dataclass
class WBCardMarkingInfo:
  found: bool
  need_kiz: bool
  title: str = ""
  nm_id: int | None = None
  error: str = ""


def _card_title(card: dict) -> str:
  return str(card.get("title") or card.get("subjectName") or "").strip()


def _card_from_match(card: dict) -> WBCardMarkingInfo:
  return WBCardMarkingInfo(
    found=True,
    need_kiz=bool(card.get("needKiz")),
    title=_card_title(card),
    nm_id=card.get("nmID"),
  )


def _match_card_by_barcode(cards: list[dict], barcode: str) -> WBCardMarkingInfo | None:
  normalized = barcode.strip()
  for card in cards:
    for size in card.get("sizes") or []:
      skus = [str(sku).strip() for sku in (size.get("skus") or [])]
      if normalized in skus:
        return _card_from_match(card)
  return None


def lookup_need_kiz(token: str, barcode: str) -> WBCardMarkingInfo:
  """POST /content/v2/get/cards/list — поле needKiz и название по баркоду."""
  barcode = barcode.strip()
  if not barcode:
    return WBCardMarkingInfo(found=False, need_kiz=False, error="Пустой баркод")

  base_url = getattr(
    settings,
    "WB_CONTENT_API_BASE_URL",
    "https://content-api.wildberries.ru",
  )
  client = WBClient(token, base_url=base_url)

  cursor: dict = {"limit": 100}
  pages = 0
  max_pages = 10

  while pages < max_pages:
    pages += 1
    try:
      payload = client._request(
        "POST",
        "/content/v2/get/cards/list",
        json={
          "settings": {
            "filter": {"textSearch": barcode, "withPhoto": -1},
            "cursor": cursor,
          },
        },
      )
    except WBApiError as exc:
      if exc.status_code == 401:
        return WBCardMarkingInfo(
          found=False,
          need_kiz=False,
          error="Токен WB недействителен. Проверьте токен селлера в админке.",
        )
      if exc.status_code == 403:
        return WBCardMarkingInfo(
          found=False,
          need_kiz=False,
          error=(
            "Токен WB не имеет доступа к категории «Контент». "
            "Создайте токен с правами «Контент» (чтение) в ЛК WB и обновите токен селлера."
          ),
        )
      return WBCardMarkingInfo(
        found=False,
        need_kiz=False,
        error=f"Ошибка запроса карточки WB: {exc}",
      )

    if not isinstance(payload, dict):
      return WBCardMarkingInfo(
        found=False,
        need_kiz=False,
        error="Неожиданный ответ WB Content API",
      )

    cards = payload.get("cards") or []
    matched = _match_card_by_barcode(cards, barcode)
    if matched:
      return matched

    response_cursor = payload.get("cursor") or {}
    total = response_cursor.get("total")
    if not cards or total is None or len(cards) >= total:
      break

    next_updated_at = response_cursor.get("updatedAt")
    next_nm_id = response_cursor.get("nmID")
    if not next_updated_at or next_nm_id is None:
      break

    cursor = {
      "limit": 100,
      "updatedAt": next_updated_at,
      "nmID": next_nm_id,
    }
    time.sleep(REQUEST_INTERVAL_SEC)

  return WBCardMarkingInfo(
    found=False,
    need_kiz=False,
    error=f"Карточка товара с баркодом «{barcode}» не найдена на WB",
  )


def _pick_photo_url(card: dict) -> str:
  photos = card.get("photos") or []
  if not photos:
    return ""
  first = photos[0] if isinstance(photos[0], dict) else {}
  for key in ("big", "c516x688", "square", "c246x328", "tm"):
    url = str(first.get(key) or "").strip()
    if url:
      return url
  return ""


def fetch_all_seller_cards(token: str, *, max_pages: int = 200) -> list[dict]:
  """Загрузить все карточки селлера из Content API (пагинация)."""
  base_url = getattr(
    settings,
    "WB_CONTENT_API_BASE_URL",
    "https://content-api.wildberries.ru",
  )
  client = WBClient(token, base_url=base_url)
  cards: list[dict] = []
  cursor: dict = {"limit": 100}
  pages = 0

  while pages < max_pages:
    pages += 1
    try:
      payload = client._request(
        "POST",
        "/content/v2/get/cards/list",
        json={
          "settings": {
            "filter": {"withPhoto": -1},
            "cursor": cursor,
          },
        },
      )
    except WBApiError as exc:
      if exc.status_code == 401:
        raise WBApiError("Токен WB недействителен") from exc
      if exc.status_code == 403:
        raise WBApiError(
          "Токен WB не имеет доступа к категории «Контент»"
        ) from exc
      raise

    if not isinstance(payload, dict):
      break

    batch = payload.get("cards") or []
    cards.extend(batch)

    response_cursor = payload.get("cursor") or {}
    total = response_cursor.get("total")
    if not batch or total is None or len(batch) >= total:
      break

    next_updated_at = response_cursor.get("updatedAt")
    next_nm_id = response_cursor.get("nmID")
    if not next_updated_at or next_nm_id is None:
      break

    cursor = {
      "limit": 100,
      "updatedAt": next_updated_at,
      "nmID": next_nm_id,
    }
    time.sleep(REQUEST_INTERVAL_SEC)

  return cards
