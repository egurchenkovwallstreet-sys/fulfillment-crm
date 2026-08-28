from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsManager
from apps.accounts.tenant import get_seller_for_user
from apps.sellers.models import Seller, SellerWarehouse
from apps.sellers.serializers import SellerWarehouseSerializer, SellerWarehouseToggleSerializer
from apps.sellers.services.sync_warehouses import WarehouseSyncError, sync_seller_warehouses


class SellerWarehouseListView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def get(self, request, seller_id):
    seller = get_seller_for_user(request.user, seller_id, active_only=True)
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)
    warehouses = SellerWarehouse.objects.filter(seller=seller).order_by("name", "wb_warehouse_id")
    return Response(SellerWarehouseSerializer(warehouses, many=True).data)


class SellerWarehouseSyncView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, seller_id):
    seller = get_seller_for_user(request.user, seller_id, active_only=True)
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)
    try:
      result = sync_seller_warehouses(seller, user=request.user)
    except WarehouseSyncError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    warehouses = SellerWarehouse.objects.filter(seller=seller).order_by("name", "wb_warehouse_id")
    return Response({
      "success": True,
      **result,
      "warehouses": SellerWarehouseSerializer(warehouses, many=True).data,
    })


class SellerWarehouseToggleView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def patch(self, request, seller_id, warehouse_id):
    seller = get_seller_for_user(request.user, seller_id, active_only=True)
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)
    warehouse = SellerWarehouse.objects.filter(pk=warehouse_id, seller=seller).first()
    if not warehouse:
      return Response(status=status.HTTP_404_NOT_FOUND)

    serializer = SellerWarehouseToggleSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    warehouse.is_enabled = serializer.validated_data["is_enabled"]
    warehouse.save(update_fields=["is_enabled", "updated_at"])

    return Response({
      "success": True,
      "warehouse": SellerWarehouseSerializer(warehouse).data,
    })
