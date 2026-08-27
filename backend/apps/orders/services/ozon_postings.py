"""Синхронизация отправлений Ozon FBS в CRM."""
from __future__ import annotations

from datetime import datetime

from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.integrations.marketplace import OZON
from apps.integrations.models import AuditLog
from apps.integrations.ozon_client import OzonApiError
from apps.orders.models import OzonPosting
from apps.orders.services.ozon_counts import OzonCountsError, ozon_client_for_seller
from apps.sellers.models import Seller, SellerOzonWarehouse
from apps.warehouse.models import Product


class OzonPostingSyncError(Exception):
  pass


def _parse_dt(value) -> datetime | None:
  if not value:
    return None
  if isinstance(value, datetime):
    return value
  parsed = parse_datetime(str(value).replace("Z", "+00:00"))
  return parsed


def _enabled_warehouse_ids(seller: Seller) -> set[int] | None:
  qs = SellerOzonWarehouse.objects.filter(seller=seller)
  if not qs.exists():
    return None
  return set(qs.filter(is_enabled=True).values_list("ozon_warehouse_id", flat=True))


def _match_product(seller: Seller, barcode: str, offer_id: str) -> Product | None:
  keys = [item for item in {barcode.strip(), offer_id.strip()} if item]
  if not keys:
    return None
  return (
    Product.objects.filter(seller=seller, marketplace=OZON)
    .filter(Q(barcode__in=keys) | Q(vendor_code__in=keys))
    .select_related("cell")
    .first()
  )


def _first_product(raw: dict) -> dict:
  products = raw.get("products") or []
  if products and isinstance(products[0], dict):
    return products[0]
  return {}


def _warehouse_id(raw: dict) -> int | None:
  method = raw.get("delivery_method") or {}
  value = method.get("warehouse_id") or raw.get("warehouse_id")
  try:
    return int(value) if value is not None else None
  except (TypeError, ValueError):
    return None


def _upsert_posting(seller: Seller, raw: dict) -> str:
  posting_number = str(raw.get("posting_number") or "").strip()
  if not posting_number:
    return "skipped"
  product_raw = _first_product(raw)
  offer_id = str(product_raw.get("offer_id") or "").strip()
  barcode = str(product_raw.get("barcode") or offer_id).strip()
  sku = product_raw.get("sku") or product_raw.get("product_id")
  mandatory = product_raw.get("mandatory_mark") or []
  ozon_status = str(raw.get("status") or "").strip()
  warehouse_id = _warehouse_id(raw)
  product = _match_product(seller, barcode, offer_id)
  if product and product.barcode:
    barcode = product.barcode

  sku_int = None
  try:
    sku_int = int(sku) if sku not in (None, "") else None
  except (TypeError, ValueError):
    sku_int = None

  crm_stage = OzonPosting.CrmStage.NEW
  if ozon_status == "awaiting_deliver":
    crm_stage = OzonPosting.CrmStage.IN_DELIVERY

  existing = OzonPosting.objects.filter(seller=seller, posting_number=posting_number).first()
  if existing:
    if existing.crm_stage == OzonPosting.CrmStage.IN_PICKING and ozon_status != "awaiting_deliver":
      crm_stage = OzonPosting.CrmStage.IN_PICKING
    if existing.crm_stage == OzonPosting.CrmStage.IN_DELIVERY:
      crm_stage = OzonPosting.CrmStage.IN_DELIVERY

  defaults = {
    "ozon_order_id": raw.get("order_id") or None,
    "ozon_status": ozon_status,
    "crm_stage": crm_stage,
    "ozon_warehouse_id": warehouse_id,
    "barcode": barcode,
    "offer_id": offer_id,
    "sku": sku_int,
    "product_name": str(product_raw.get("name") or "")[:500],
    "quantity": int(product_raw.get("quantity") or 1) if str(product_raw.get("quantity") or "1").isdigit() else 1,
    "requires_marking": bool(mandatory) or bool(product.requires_marking if product else False),
    "product": product,
    "shipment_date": _parse_dt(raw.get("shipment_date") or raw.get("delivering_date")),
    "in_process_at": _parse_dt(raw.get("in_process_at")),
  }
  _, created = OzonPosting.objects.update_or_create(
    seller=seller,
    posting_number=posting_number,
    defaults=defaults,
  )
  return "created" if created else "updated"


def sync_ozon_postings(seller: Seller, *, user=None) -> dict:
  try:
    client = ozon_client_for_seller(seller)
    packaging = client.list_postings("awaiting_packaging")
    delivering = client.list_postings("awaiting_deliver")
  except (OzonCountsError, OzonApiError) as exc:
    raise OzonPostingSyncError(str(exc)) from exc

  enabled_ids = _enabled_warehouse_ids(seller)
  created = updated = skipped = 0
  seen: set[str] = set()
  for raw in packaging + delivering:
    if not isinstance(raw, dict):
      continue
    warehouse_id = _warehouse_id(raw)
    if enabled_ids is not None and warehouse_id and warehouse_id not in enabled_ids:
      skipped += 1
      continue
    result = _upsert_posting(seller, raw)
    number = str(raw.get("posting_number") or "")
    if number:
      seen.add(number)
    if result == "created":
      created += 1
    elif result == "updated":
      updated += 1

  picking_ids = list(
    OzonPosting.objects.filter(
      seller=seller,
      crm_stage=OzonPosting.CrmStage.IN_PICKING,
    ).values_list("id", flat=True)
  )
  new_count = OzonPosting.objects.filter(
    seller=seller,
    crm_stage=OzonPosting.CrmStage.NEW,
    ozon_status="awaiting_packaging",
  ).count()
  delivery_count = OzonPosting.objects.filter(
    seller=seller,
    crm_stage=OzonPosting.CrmStage.IN_DELIVERY,
  ).count()

  seller.ozon_count_new = new_count
  seller.ozon_count_assembly = len(picking_ids)
  seller.ozon_count_delivery = delivery_count
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

  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.OTHER,
    message=f"Синхронизация отправлений Ozon: {len(seen)} шт.",
    details={"created": created, "updated": updated, "skipped": skipped},
  )
  return {
    "created": created,
    "updated": updated,
    "skipped": skipped,
    "new": new_count,
    "in_picking": len(picking_ids),
    "in_delivery": delivery_count,
  }


def serialize_ozon_posting(posting: OzonPosting) -> dict:
  cell_number = ""
  photo_url = ""
  tech_size = ""
  if posting.product_id:
    cell_number = posting.product.cell.number if posting.product.cell_id else ""
    photo_url = posting.product.photo_url or ""
    tech_size = posting.product.tech_size or posting.product.wb_size or ""
  stage_label = {
    OzonPosting.CrmStage.NEW: "Новый",
    OzonPosting.CrmStage.IN_PICKING: "На сборке",
    OzonPosting.CrmStage.IN_DELIVERY: "В доставке",
  }.get(posting.crm_stage, posting.crm_stage)
  return {
    "id": posting.id,
    "wb_order_id": posting.id,
    "posting_number": posting.posting_number,
    "barcode": posting.barcode,
    "offer_id": posting.offer_id,
    "sku": posting.sku,
    "product_name": posting.product_name,
    "photo_url": photo_url,
    "tech_size": tech_size,
    "cell_number": cell_number or "—",
    "quantity": posting.quantity,
    "status": posting.crm_stage,
    "status_display": stage_label,
    "wb_supplier_status": posting.ozon_status,
    "wb_status": posting.ozon_status,
    "wb_stage_display": posting.ozon_status,
    "has_sticker": False,
    "sticker_part_a": "",
    "sticker_part_b": "",
    "marking_bound": posting.marking_bound,
    "requires_marking": posting.requires_marking,
    "can_send_to_assembly": posting.crm_stage == OzonPosting.CrmStage.NEW,
    "can_send_to_delivery": posting.crm_stage == OzonPosting.CrmStage.IN_PICKING,
    "warehouse_quantity": posting.product.quantity if posting.product_id else None,
    "created_at": posting.created_at.isoformat() if posting.created_at else "",
  }
