"""Сборка FBS Ozon: скан в «На сборке» и ship в «В доставку»."""
from __future__ import annotations

from django.db import transaction

from apps.integrations.ozon_client import OzonApiError
from apps.orders.models import OzonPosting
from apps.orders.services.ozon_counts import OzonCountsError, ozon_client_for_seller
from apps.orders.services.ozon_postings import serialize_ozon_posting
from apps.warehouse.models import StockOperation


class OzonAssemblyError(Exception):
  pass


def _seller_counts(seller) -> dict[str, int]:
  return {
    "new": OzonPosting.objects.filter(
      seller=seller, crm_stage=OzonPosting.CrmStage.NEW, ozon_status="awaiting_packaging",
    ).count(),
    "in_picking": OzonPosting.objects.filter(
      seller=seller, crm_stage=OzonPosting.CrmStage.IN_PICKING,
    ).count(),
    "in_delivery": OzonPosting.objects.filter(
      seller=seller, crm_stage=OzonPosting.CrmStage.IN_DELIVERY,
    ).count(),
  }


def _save_seller_counts(seller) -> dict[str, int]:
  counts = _seller_counts(seller)
  seller.ozon_count_new = counts["new"]
  seller.ozon_count_assembly = counts["in_picking"]
  seller.ozon_count_delivery = counts["in_delivery"]
  seller.save(
    update_fields=[
      "ozon_count_new",
      "ozon_count_assembly",
      "ozon_count_delivery",
      "updated_at",
    ]
  )
  return counts


@transaction.atomic
def scan_ozon_barcode(seller, barcode: str) -> dict:
  code = (barcode or "").strip()
  if not code:
    raise OzonAssemblyError("Отсканируйте баркод")
  posting = (
    OzonPosting.objects.select_related("product", "product__cell")
    .filter(seller=seller, barcode=code, crm_stage=OzonPosting.CrmStage.NEW)
    .order_by("in_process_at")
    .first()
  )
  if not posting:
    posting = (
      OzonPosting.objects.select_related("product", "product__cell")
      .filter(seller=seller, offer_id=code, crm_stage=OzonPosting.CrmStage.NEW)
      .order_by("in_process_at")
      .first()
    )
  if not posting:
    posting = (
      OzonPosting.objects.select_related("product", "product__cell")
      .filter(seller=seller, product__barcode=code, crm_stage=OzonPosting.CrmStage.NEW)
      .order_by("in_process_at")
      .first()
    )
  if not posting:
    raise OzonAssemblyError("Отправление с этим баркодом не найдено во вкладке «Новые»")
  posting.crm_stage = OzonPosting.CrmStage.IN_PICKING
  posting.save(update_fields=["crm_stage", "updated_at"])
  counts = _save_seller_counts(seller)
  return {
    "success": True,
    "message": f"Отправление {posting.posting_number} на сборке",
    "posting": serialize_ozon_posting(posting),
    "counts": counts,
  }


def ship_ozon_posting(seller, posting_id: int, *, user=None) -> dict:
  posting = (
    OzonPosting.objects.select_related("product", "product__cell")
    .filter(pk=posting_id, seller=seller)
    .first()
  )
  if not posting:
    raise OzonAssemblyError("Отправление не найдено")
  if posting.crm_stage != OzonPosting.CrmStage.IN_PICKING:
    raise OzonAssemblyError("Сначала отсканируйте отправление на сборке")
  if posting.requires_marking and not posting.marking_bound:
    raise OzonAssemblyError("Сначала привяжите Честный знак")
  if not posting.sku:
    raise OzonAssemblyError("У отправления нет SKU Ozon — обновите данные")

  packages = [{
    "products": [{
      "product_id": posting.sku,
      "quantity": posting.quantity or 1,
    }],
  }]
  if posting.requires_marking and posting.marking_code:
    packages[0]["products"][0]["exemplar_info"] = [{
      "mandatory_mark": posting.marking_code,
    }]

  try:
    client = ozon_client_for_seller(seller)
    client.ship_posting(posting.posting_number, packages)
  except (OzonCountsError, OzonApiError) as exc:
    raise OzonAssemblyError(str(exc)) from exc

  posting.ozon_status = "awaiting_deliver"
  posting.crm_stage = OzonPosting.CrmStage.IN_DELIVERY
  update_fields = ["ozon_status", "crm_stage", "updated_at"]

  stock = None
  product = posting.product
  if product and not posting.stock_deducted:
    qty = posting.quantity or 1
    product.quantity = max(0, (product.quantity or 0) - qty)
    product.save(update_fields=["quantity", "updated_at"])
    StockOperation.objects.create(
      product=product,
      operation_type=StockOperation.OperationType.SHIPMENT,
      quantity=-qty,
      performed_by=user,
      comment=f"Ozon {posting.posting_number}",
    )
    posting.stock_deducted = True
    update_fields.append("stock_deducted")
    stock = {
      "deducted": True,
      "already_deducted": False,
      "quantity": qty,
      "cell_number": product.cell.number if product.cell_id else "",
      "barcode": product.barcode,
    }

  posting.save(update_fields=update_fields)
  counts = _save_seller_counts(seller)
  return {
    "success": True,
    "message": f"{posting.posting_number} передано к отгрузке (ожидает сдачи в пункт Ozon)",
    "posting": serialize_ozon_posting(posting),
    "counts": counts,
    "stock": stock,
  }
