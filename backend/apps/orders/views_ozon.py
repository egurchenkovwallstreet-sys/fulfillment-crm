from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsManager
from apps.orders.models import OzonPosting
from apps.orders.services.ozon_assembly import OzonAssemblyError, scan_ozon_barcode, ship_ozon_posting
from apps.orders.services.ozon_postings import serialize_ozon_posting, sync_ozon_postings
from apps.sellers.models import Seller, SellerOzonWarehouse
from apps.sellers.serializers import SellerOzonWarehouseSerializer
from apps.sellers.services.sync_ozon_warehouses import OzonWarehouseSyncError, sync_seller_ozon_warehouses


def _ozon_stage_qs(seller, stage: str):
  qs = OzonPosting.objects.filter(seller=seller).select_related("product", "product__cell")
  if stage in ("new", ""):
    return qs.filter(crm_stage=OzonPosting.CrmStage.NEW, ozon_status="awaiting_packaging")
  if stage in ("confirm", "in_picking"):
    return qs.filter(crm_stage=OzonPosting.CrmStage.IN_PICKING)
  if stage in ("complete", "in_delivery"):
    return qs.filter(crm_stage=OzonPosting.CrmStage.IN_DELIVERY)
  return qs


class OzonAssemblySellerDetailView:
  """Mixin-like helpers used from AssemblySellerDetailView."""

  @staticmethod
  def payload(seller, stage: str) -> dict:
    from apps.orders.services.ozon_counts import get_seller_ozon_tab_counts

    tab_counts = get_seller_ozon_tab_counts(seller)
    orders = [
      serialize_ozon_posting(item)
      for item in _ozon_stage_qs(seller, stage or "new").order_by("in_process_at", "id")[:300]
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
    seller = Seller.objects.filter(pk=seller_id, is_active=True).first()
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)
    barcode = str(request.data.get("barcode") or "")
    try:
      result = scan_ozon_barcode(seller, barcode)
    except OzonAssemblyError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)


class OzonAssemblyShipView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, seller_id):
    seller = Seller.objects.filter(pk=seller_id, is_active=True).first()
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)
    posting_id = request.data.get("posting_id") or request.data.get("order_id")
    try:
      result = ship_ozon_posting(seller, int(posting_id), user=request.user)
    except (OzonAssemblyError, TypeError, ValueError) as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)


class OzonAssemblySyncView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, seller_id):
    seller = Seller.objects.filter(pk=seller_id, is_active=True).first()
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
