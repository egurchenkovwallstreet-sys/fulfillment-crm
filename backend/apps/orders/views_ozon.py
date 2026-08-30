from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsManager
from apps.accounts.tenant import get_seller_for_user
from apps.orders.models import OzonPosting
from apps.orders.services.ozon_act import OzonActError, fetch_ozon_act_docs, form_ozon_acts
from apps.orders.services.ozon_assembly import (
  OzonAssemblyError,
  bind_ozon_marking,
  bulk_move_ozon_to_assembly,
  bulk_ship_ozon_postings,
  fetch_ozon_label,
  fetch_ozon_labels_bulk,
  scan_ozon_barcode,
  ship_ozon_posting,
)
from apps.orders.services.ozon_postings import serialize_ozon_posting, sync_ozon_postings
from apps.sellers.models import SellerOzonWarehouse
from apps.sellers.serializers import SellerOzonWarehouseSerializer
from apps.sellers.services.sync_ozon_warehouses import OzonWarehouseSyncError, sync_seller_ozon_warehouses


def _ozon_stage_qs(seller, stage: str, *, assembly_only: bool = False):
  qs = OzonPosting.objects.filter(seller=seller).select_related("product", "product__cell")
  if assembly_only:
    from apps.orders.services.ozon_postings import _enabled_warehouse_ids

    enabled_ids = _enabled_warehouse_ids(seller)
    if enabled_ids is not None:
      qs = qs.filter(ozon_warehouse_id__in=enabled_ids)
  if stage in ("new", ""):
    return qs.filter(crm_stage=OzonPosting.CrmStage.NEW, ozon_status="awaiting_packaging")
  if stage in ("confirm", "in_picking"):
    return qs.filter(crm_stage=OzonPosting.CrmStage.IN_PICKING)
  if stage in ("complete", "in_delivery"):
    return qs.filter(crm_stage=OzonPosting.CrmStage.IN_DELIVERY)
  return qs


def _error_response(exc: Exception):
  payload = {"detail": str(exc)}
  code = getattr(exc, "code", "") or ""
  if code:
    payload["code"] = code
  return Response(payload, status=status.HTTP_400_BAD_REQUEST)


class OzonAssemblySellerDetailView:
  """Mixin-like helpers used from AssemblySellerDetailView."""

  @staticmethod
  def payload(seller, stage: str) -> dict:
    from apps.orders.services.ozon_counts import get_seller_ozon_tab_counts

    tab_counts = get_seller_ozon_tab_counts(seller, assembly_only=True)
    orders = [
      serialize_ozon_posting(item, seller=seller)
      for item in _ozon_stage_qs(seller, stage or "new", assembly_only=True).order_by("in_process_at", "id")[:300]
    ]
    warehouses = SellerOzonWarehouse.objects.filter(seller=seller).order_by("name", "ozon_warehouse_id")
    return {
      "seller": {"id": seller.id, "company_name": seller.company_name},
      "marketplace": "ozon",
      "ozon_assembly_ready": True,
      "counts": {
        "new": tab_counts["new"],
        "in_picking": tab_counts["in_picking"],
        "in_delivery": tab_counts["in_delivery"],
      },
      "assembly_eligible": tab_counts["new"],
      "orders": orders,
      "pick_list": None,
      "active_pick_list": None,
      "supplies_forming": 0,
      "warehouses": SellerOzonWarehouseSerializer(warehouses, many=True).data,
    }


class OzonAssemblyScanView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, seller_id):
    seller = get_seller_for_user(request.user, seller_id, active_only=True)
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)
    barcode = str(request.data.get("barcode") or "")
    posting_ids = request.data.get("posting_ids") or []
    try:
      if posting_ids:
        ids = [int(item) for item in posting_ids]
        result = bulk_move_ozon_to_assembly(seller, ids)
      else:
        result = scan_ozon_barcode(seller, barcode)
    except (OzonAssemblyError, TypeError, ValueError) as exc:
      return _error_response(exc)
    return Response(result)


class OzonAssemblyBindMarkingView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, seller_id):
    seller = get_seller_for_user(request.user, seller_id, active_only=True)
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)
    posting_id = request.data.get("posting_id") or request.data.get("order_id")
    marking_code = str(request.data.get("marking_code") or request.data.get("barcode") or "")
    try:
      result = bind_ozon_marking(seller, int(posting_id), marking_code)
    except (OzonAssemblyError, TypeError, ValueError) as exc:
      return _error_response(exc)
    return Response(result)


class OzonAssemblyShipView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, seller_id):
    seller = get_seller_for_user(request.user, seller_id, active_only=True)
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)
    posting_id = request.data.get("posting_id") or request.data.get("order_id")
    posting_ids = request.data.get("posting_ids") or []
    try:
      if posting_ids:
        result = bulk_ship_ozon_postings(
          seller,
          [int(item) for item in posting_ids],
          user=request.user,
        )
      else:
        result = ship_ozon_posting(seller, int(posting_id), user=request.user)
    except (OzonAssemblyError, TypeError, ValueError) as exc:
      return _error_response(exc)
    return Response(result)


class OzonAssemblyLabelView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, seller_id):
    seller = get_seller_for_user(request.user, seller_id, active_only=True)
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)
    posting_ids = request.data.get("posting_ids") or []
    posting_id = request.data.get("posting_id") or request.data.get("order_id")
    try:
      if posting_ids:
        ids = [int(item) for item in posting_ids]
        result = fetch_ozon_labels_bulk(seller, ids)
      else:
        result = fetch_ozon_label(seller, int(posting_id))
    except (OzonAssemblyError, TypeError, ValueError) as exc:
      return _error_response(exc)
    return Response(result)


class OzonAssemblyActView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, seller_id):
    seller = get_seller_for_user(request.user, seller_id, active_only=True)
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)
    carriage_id = request.data.get("carriage_id")
    try:
      if carriage_id:
        result = fetch_ozon_act_docs(seller, int(carriage_id))
      else:
        result = form_ozon_acts(seller)
    except (OzonActError, TypeError, ValueError) as exc:
      return _error_response(exc)
    return Response(result)


class OzonAssemblySyncView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, seller_id):
    seller = get_seller_for_user(request.user, seller_id, active_only=True)
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)
    warning = ""
    try:
      sync_seller_ozon_warehouses(seller, user=request.user)
    except OzonWarehouseSyncError as exc:
      warning = str(exc)
    from apps.orders.services.ozon_postings import OzonPostingSyncError

    try:
      stats = sync_ozon_postings(seller, user=request.user)
    except OzonPostingSyncError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    stage = str(request.data.get("stage") or "new")
    payload = OzonAssemblySellerDetailView.payload(seller, stage)
    payload["sync"] = stats
    if warning:
      payload["warehouse_warning"] = warning
    return Response(payload)
