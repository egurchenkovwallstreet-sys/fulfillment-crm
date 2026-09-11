"""Клиент Content API Wildberries — карточки товаров, needKiz."""
from __future__ import annotations

import time
from dataclasses import dataclass

from django.conf import settings

from apps.integrations.wb_client import WBApiError, WBClient, REQUEST_INTERVAL_SEC

PAGE_LIMIT = 100


@dataclass
class WBCardMarkingInfo:
  found: bool
  need_kiz: bool
  title: str = ""
  nm_id: int | None = None
  error: str = ""


def _content_base_url() -> str:
  return getattr(
    settings,
    "WB_CONTENT_API_BASE_URL",
    "https://content-api.wildberries.ru",
  )


def _card_title(card: dict) -> str:
  return str(card.get("title") or card.get("subjectName") or "").strip()


def _card_from_match(card: dict) -> WBCardMarkingInfo:
  return WBCardMarkingInfo(
    found=True,
    need_kiz=bool(card.get("needKiz")),
    title=_card_title(card),
    nm_id=card.get("nmID"),
  )


def _find_card_by_barcode(cards: list[dict], barcode: str) -> dict | None:
  normalized = barcode.strip()
  for card in cards:
    for size in card.get("sizes") or []:
      skus = [str(sku).strip() for sku in (size.get("skus") or [])]
      if normalized in skus:
        return card
  return None


def _has_next_page(batch: list[dict], response_cursor: dict, *, limit: int = PAGE_LIMIT) -> bool:
  if len(batch) < limit:
    return False
  updated_at = response_cursor.get("updatedAt")
  nm_id = response_cursor.get("nmID")
  return bool(updated_at and nm_id is not None)


def _next_cursor(response_cursor: dict, *, limit: int = PAGE_LIMIT) -> dict:
  return {
    "limit": limit,
    "updatedAt": response_cursor.get("updatedAt"),
    "nmID": response_cursor.get("nmID"),
  }


def _request_cards_page(
  client: WBClient,
  *,
  filter_dict: dict,
  cursor: dict,
) -> tuple[list[dict], dict]:
  payload = client._request(
    "POST",
    "/content/v2/get/cards/list",
    json={
      "settings": {
        "filter": filter_dict,
        "cursor": cursor,
      },
    },
  )
  if not isinstance(payload, dict):
    return [], {}
  return payload.get("cards") or [], payload.get("cursor") or {}


def _map_content_api_error(exc: WBApiError) -> WBCardMarkingInfo:
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


def search_wb_card_by_barcode(token: str, barcode: str, *, max_pages: int = 10) -> dict | None:
  """Найти полную карточку WB по баркоду (Content API, textSearch + пагинация)."""
  barcode = barcode.strip()
  if not barcode:
    return None

  client = WBClient(token, base_url=_content_base_url())
  cursor: dict = {"limit": PAGE_LIMIT}
  pages = 0

  while pages < max_pages:
    pages += 1
    try:
      cards, response_cursor = _request_cards_page(
        client,
        filter_dict={"textSearch": barcode, "withPhoto": -1},
        cursor=cursor,
      )
    except WBApiError:
      return None

    matched = _find_card_by_barcode(cards, barcode)
    if matched:
      return matched

    if not _has_next_page(cards, response_cursor):
      break

    cursor = _next_cursor(response_cursor)
    time.sleep(REQUEST_INTERVAL_SEC)

  return None


def lookup_need_kiz(token: str, barcode: str) -> WBCardMarkingInfo:
  """POST /content/v2/get/cards/list — поле needKiz и название по баркоду."""
  barcode = barcode.strip()
  if not barcode:
    return WBCardMarkingInfo(found=False, need_kiz=False, error="Пустой баркод")

  client = WBClient(token, base_url=_content_base_url())
  cursor: dict = {"limit": PAGE_LIMIT}
  pages = 0
  max_pages = 10

  while pages < max_pages:
    pages += 1
    try:
      cards, response_cursor = _request_cards_page(
        client,
        filter_dict={"textSearch": barcode, "withPhoto": -1},
        cursor=cursor,
      )
    except WBApiError as exc:
      return _map_content_api_error(exc)

    matched = _find_card_by_barcode(cards, barcode)
    if matched:
      return _card_from_match(matched)

    if not _has_next_page(cards, response_cursor):
      break

    cursor = _next_cursor(response_cursor)
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
  client = WBClient(token, base_url=_content_base_url())
  cards: list[dict] = []
  cursor: dict = {"limit": PAGE_LIMIT}
  pages = 0

  while pages < max_pages:
    pages += 1
    try:
      batch, response_cursor = _request_cards_page(
        client,
        filter_dict={"withPhoto": -1},
        cursor=cursor,
      )
    except WBApiError as exc:
      if exc.status_code == 401:
        raise WBApiError("Токен WB недействителен") from exc
      if exc.status_code == 403:
        raise WBApiError(
          "Токен WB не имеет доступа к категории «Контент»"
        ) from exc
      raise

    cards.extend(batch)

    if not _has_next_page(batch, response_cursor):
      break

    cursor = _next_cursor(response_cursor)
    time.sleep(REQUEST_INTERVAL_SEC)

  return cards
