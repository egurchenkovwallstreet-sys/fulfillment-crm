from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsAdmin
from apps.integrations.wb_crypto import encrypt_token
from apps.orders.services.ozon_counts import OzonCountsError, ping_seller_ozon, refresh_ozon_counts
from apps.sellers.models import Seller
from apps.sellers.serializers import SellerManageSerializer


class SellerMarketplaceFlagsView(APIView):
  permission_classes = [IsAuthenticated, IsAdmin]

  def patch(self, request, seller_id):
    seller = Seller.objects.filter(pk=seller_id).first()
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
    seller = Seller.objects.filter(pk=seller_id).first()
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
