"""Клиент Content API Wildberries — карточки товаров, needKiz."""
from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings

from apps.integrations.wb_client import WBApiError, WBClient


@dataclass
class WBCardMarkingInfo:
  found: bool
  need_kiz: bool
  title: str = ""
  nm_id: int | None = None
  error: str = ""


def lookup_need_kiz(token: str, barcode: str) -> WBCardMarkingInfo:
  """POST /content/v2/get/cards/list — поле needKiz по баркоду."""
  barcode = barcode.strip()
  if not barcode:
    return WBCardMarkingInfo(found=False, need_kiz=False, error="Пустой баркод")

  base_url = getattr(
    settings,
    "WB_CONTENT_API_BASE_URL",
    "https://content-api.wildberries.ru",
  )
  client = WBClient(token, base_url=base_url)

  try:
    payload = client._request(
      "POST",
      "/content/v2/get/cards/list",
      json={
        "settings": {
          "filter": {"textSearch": barcode, "withPhoto": -1},
          "cursor": {"limit": 20},
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
  if not cards:
    return WBCardMarkingInfo(
      found=False,
      need_kiz=False,
      error=f"Карточка товара с баркодом «{barcode}» не найдена на WB",
    )

  matched = _match_card_by_barcode(cards, barcode)
  if matched:
    return matched

  card = cards[0]
  return WBCardMarkingInfo(
    found=True,
    need_kiz=bool(card.get("needKiz")),
    title=str(card.get("title") or ""),
    nm_id=card.get("nmID"),
  )


def _match_card_by_barcode(cards: list[dict], barcode: str) -> WBCardMarkingInfo | None:
  for card in cards:
    for size in card.get("sizes") or []:
      skus = [str(sku).strip() for sku in (size.get("skus") or [])]
      if barcode in skus:
        return WBCardMarkingInfo(
          found=True,
          need_kiz=bool(card.get("needKiz")),
          title=str(card.get("title") or ""),
          nm_id=card.get("nmID"),
        )
  return None
