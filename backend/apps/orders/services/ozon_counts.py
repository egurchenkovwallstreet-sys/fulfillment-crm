"""Кэш счётчиков Ozon FBS на селлере."""
from __future__ import annotations

import logging

from django.utils import timezone

from apps.integrations.ozon_client import OzonApiError, OzonClient
from apps.integrations.wb_crypto import TokenCryptoError, decrypt_token
from apps.sellers.models import Seller

logger = logging.getLogger(__name__)


class OzonCountsError(Exception):
  pass


def seller_ozon_credentials(seller: Seller) -> tuple[str, str]:
  client_id = (seller.ozon_client_id or "").strip()
  if not client_id:
    raise OzonCountsError("Не задан Client-Id Ozon")
  try:
    api_key = decrypt_token(seller.ozon_api_key_encrypted or "")
  except TokenCryptoError as exc:
    raise OzonCountsError("Не удалось расшифровать Api-Key Ozon") from exc
  if not api_key:
    raise OzonCountsError("Не задан Api-Key Ozon")
  return client_id, api_key


def ozon_client_for_seller(seller: Seller) -> OzonClient:
  client_id, api_key = seller_ozon_credentials(seller)
  return OzonClient(client_id, api_key)


def ping_seller_ozon(seller: Seller) -> dict:
  client = ozon_client_for_seller(seller)
  try:
    return client.ping()
  except OzonApiError as exc:
    raise OzonCountsError(str(exc)) from exc


def refresh_ozon_counts(seller: Seller) -> dict[str, int]:
  client = ozon_client_for_seller(seller)
  try:
    counts = client.posting_tab_counts()
  except OzonApiError as exc:
    raise OzonCountsError(str(exc)) from exc

  seller.ozon_count_new = counts["new"]
  seller.ozon_count_assembly = counts["in_picking"]
  seller.ozon_count_delivery = counts["in_delivery"]
  seller.ozon_counts_synced_at = timezone.now()
  seller.save(
    update_fields=[
      "ozon_count_new",
      "ozon_count_assembly",
      "ozon_count_delivery",
      "ozon_counts_synced_at",
      "updated_at",
    ]
  )
  return counts


def get_seller_ozon_tab_counts(seller: Seller, *, assembly_only: bool = False) -> dict[str, int]:
  if not assembly_only:
    return {
      "new": seller.ozon_count_new or 0,
      "in_picking": seller.ozon_count_assembly or 0,
      "in_delivery": seller.ozon_count_delivery or 0,
    }

  from apps.orders.models import OzonPosting
  from apps.orders.services.ozon_postings import _enabled_warehouse_ids

  qs = OzonPosting.objects.filter(seller=seller)
  enabled_ids = _enabled_warehouse_ids(seller)
  if enabled_ids is not None:
    qs = qs.filter(ozon_warehouse_id__in=enabled_ids)
  return {
    "new": qs.filter(
      crm_stage=OzonPosting.CrmStage.NEW,
      ozon_status="awaiting_packaging",
    ).count(),
    "in_picking": qs.filter(crm_stage=OzonPosting.CrmStage.IN_PICKING).count(),
    "in_delivery": qs.filter(crm_stage=OzonPosting.CrmStage.IN_DELIVERY).count(),
  }


def _stage_totals_ozon(sellers) -> tuple[dict[str, int], object | None]:
  totals = {"new": 0, "in_picking": 0, "in_delivery": 0}
  latest_sync = None
  for seller in sellers:
    counts = get_seller_ozon_tab_counts(seller)
    totals["new"] += counts["new"]
    totals["in_picking"] += counts["in_picking"]
    totals["in_delivery"] += counts["in_delivery"]
    if seller.ozon_counts_synced_at and (
      latest_sync is None or seller.ozon_counts_synced_at > latest_sync
    ):
      latest_sync = seller.ozon_counts_synced_at
  return totals, latest_sync
