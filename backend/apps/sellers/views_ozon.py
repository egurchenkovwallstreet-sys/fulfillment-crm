from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsAdmin, IsManager
from apps.accounts.tenant import get_seller_for_user
from apps.integrations.wb_crypto import encrypt_token
from apps.orders.services.ozon_counts import OzonCountsError, ping_seller_ozon, refresh_ozon_counts
from apps.sellers.models import Seller, SellerOzonWarehouse
from apps.sellers.serializers import SellerManageSerializer, SellerOzonWarehouseSerializer, SellerWarehouseToggleSerializer
from apps.sellers.services.sync_ozon_warehouses import OzonWarehouseSyncError, sync_seller_ozon_warehouses


class SellerMarketplaceFlagsView(APIView):
  permission_classes = [IsAuthenticated, IsAdmin]

  def patch(self, request, seller_id):
    seller = get_seller_for_user(request.user, seller_id)
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)

    wb_enabled = request.data.get("wb_enabled")
    ozon_enabled = request.data.get("ozon_enabled")
    if wb_enabled is not None:
      seller.wb_enabled = bool(wb_enabled)
    if ozon_enabled is not None:
      seller.ozon_enabled = bool(ozon_enabled)
    if not seller.wb_enabled and not seller.ozon_enabled:
      return Response(
        {"detail": "Оставьте хотя бы один маркетплейс"},
        status=status.HTTP_400_BAD_REQUEST,
      )
    seller.save(update_fields=["wb_enabled", "ozon_enabled", "updated_at"])
    return Response(SellerManageSerializer(seller).data)


class SellerOzonKeysView(APIView):
  permission_classes = [IsAuthenticated, IsAdmin]

  def post(self, request, seller_id):
    seller = get_seller_for_user(request.user, seller_id)
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)

    client_id = str(request.data.get("client_id") or "").strip()
    api_key = str(request.data.get("api_key") or "").strip()
    if not client_id or not api_key:
      return Response(
        {"detail": "Укажите Client-Id и Api-Key из ЛК Ozon"},
        status=status.HTTP_400_BAD_REQUEST,
      )

    seller.ozon_client_id = client_id
    seller.ozon_api_key_encrypted = encrypt_token(api_key)
    seller.ozon_enabled = True
    seller.save(
      update_fields=[
        "ozon_client_id",
        "ozon_api_key_encrypted",
        "ozon_enabled",
        "updated_at",
      ]
    )

    ping_ok = False
    ping_detail = ""
    counts = None
    try:
      ping_seller_ozon(seller)
      ping_ok = True
      counts = refresh_ozon_counts(seller)
    except OzonCountsError as exc:
      ping_detail = str(exc)

    payload = SellerManageSerializer(seller).data
    return Response({
      "success": True,
      "ping_ok": ping_ok,
      "detail": (
        "Ключи сохранены. API Ozon отвечает."
        if ping_ok
        else f"Ключи сохранены, но проверка API не прошла: {ping_detail}"
      ),
      "counts": counts,
      "seller": payload,
    })


class SellerOzonWarehouseListView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def get(self, request, seller_id):
    seller = get_seller_for_user(request.user, seller_id, active_only=True)
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)
    warehouses = SellerOzonWarehouse.objects.filter(seller=seller).order_by("name", "ozon_warehouse_id")
    return Response(SellerOzonWarehouseSerializer(warehouses, many=True).data)


class SellerOzonWarehouseSyncView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, seller_id):
    seller = get_seller_for_user(request.user, seller_id, active_only=True)
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)
    try:
      result = sync_seller_ozon_warehouses(seller, user=request.user)
    except OzonWarehouseSyncError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    warehouses = SellerOzonWarehouse.objects.filter(seller=seller).order_by("name", "ozon_warehouse_id")
    return Response({
      "success": True,
      **result,
      "warehouses": SellerOzonWarehouseSerializer(warehouses, many=True).data,
    })


class SellerOzonWarehouseToggleView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def patch(self, request, seller_id, warehouse_id):
    seller = get_seller_for_user(request.user, seller_id, active_only=True)
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)
    warehouse = SellerOzonWarehouse.objects.filter(pk=warehouse_id, seller=seller).first()
    if not warehouse:
      return Response(status=status.HTTP_404_NOT_FOUND)
    serializer = SellerWarehouseToggleSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    warehouse.is_enabled = serializer.validated_data["is_enabled"]
    warehouse.save(update_fields=["is_enabled", "updated_at"])
    return Response({
      "success": True,
      "warehouse": SellerOzonWarehouseSerializer(warehouse).data,
    })
