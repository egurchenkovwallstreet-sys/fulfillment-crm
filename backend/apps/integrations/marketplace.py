"""Маркетплейс текущего запроса: WB или Ozon."""
from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import QuerySet

if TYPE_CHECKING:
  from apps.sellers.models import Seller

WB = "wb"
OZON = "ozon"
CHOICES = (
  (WB, "Wildberries"),
  (OZON, "Ozon"),
)
LABELS = {WB: "ВБ", OZON: "OZON"}
HEADER = "X-Marketplace"


def normalize_marketplace(value: str | None) -> str:
  raw = (value or "").strip().lower()
  if raw in {OZON, "озон"}:
    return OZON
  return WB


def parse_marketplace(request) -> str:
  header = request.headers.get(HEADER) if hasattr(request, "headers") else None
  query = None
  if hasattr(request, "query_params"):
    query = request.query_params.get("marketplace")
  elif hasattr(request, "GET"):
    query = request.GET.get("marketplace")
  body = None
  data = getattr(request, "data", None)
  if isinstance(data, dict):
    body = data.get("marketplace")
  return normalize_marketplace(header or query or body)


def marketplace_label(marketplace: str) -> str:
  return LABELS.get(normalize_marketplace(marketplace), LABELS[WB])


def filter_sellers_qs(qs: QuerySet, marketplace: str) -> QuerySet:
  mp = normalize_marketplace(marketplace)
  if mp == OZON:
    return qs.filter(ozon_enabled=True)
  return qs.filter(wb_enabled=True)


def seller_allows_marketplace(seller: Seller | None, marketplace: str) -> bool:
  if seller is None:
    return True
  mp = normalize_marketplace(marketplace)
  if mp == OZON:
    return bool(seller.ozon_enabled)
  return bool(seller.wb_enabled)
