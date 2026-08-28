import logging

from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsAdmin, IsSeller
from apps.accounts.serializers import UserSerializer
from apps.sellers.models import Seller
from apps.sellers.serializers import (
  AdminBillingDashboardSerializer,
  SellerBarcodeAnalyticsSerializer,
  SellerBarcodeDetailSerializer,
  SellerCabinetSummarySerializer,
  SellerCreateSerializer,
  SellerInviteSerializer,
  SellerManageSerializer,
  SellerRegisterSerializer,
  SellerUpdateSerializer,
  SellerWeeklyShipmentsSerializer,
  SellerWbStageCountsSerializer,
)
from apps.integrations.wb_crypto import encrypt_token
from apps.sellers.services.sync_warehouses import WarehouseSyncError, sync_seller_warehouses
from apps.sellers.services.invite import (
  deactivate_invite,
  ensure_seller_invite,
  get_invite_by_token,
  issue_seller_invite,
)
from apps.sellers.services.seller_analytics import build_barcode_detail, build_seller_cabinet_payload
from apps.sellers.services.seller_billing_stats import load_admin_billing_dashboard
from apps.sellers.services.wb_order_stats import SellerAnalyticsError, get_enabled_warehouses_meta, load_wb_fbs_stats
from apps.sellers.utils import seller_has_user_account, seller_username

User = get_user_model()
logger = logging.getLogger(__name__)


def _invite_path(request, token: str) -> str:
  return f"{request.scheme}://{request.get_host()}/register/{token}"


def _seller_queryset():
  return Seller.objects.select_related("user_account").select_related("invite")


class SellerManageListCreateView(APIView):
  permission_classes = [IsAuthenticated, IsAdmin]

  def get(self, request):
    sellers = _seller_queryset().order_by("company_name")
    for seller in sellers:
      ensure_seller_invite(seller)
    sellers = _seller_queryset().order_by("company_name")
    return Response(SellerManageSerializer(sellers, many=True).data)

  def post(self, request):
    serializer = SellerCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    seller = serializer.save()
    invite = ensure_seller_invite(seller)
    payload = SellerManageSerializer(seller).data
    payload["invite_url"] = _invite_path(request, invite.token)
    return Response(payload, status=status.HTTP_201_CREATED)


class SellerManageDetailView(APIView):
  permission_classes = [IsAuthenticated, IsAdmin]

  def patch(self, request, seller_id):
    seller = Seller.objects.select_related("user_account").filter(pk=seller_id).first()
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)
    serializer = SellerUpdateSerializer(seller, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(SellerManageSerializer(seller).data)


class SellerWbTokenView(APIView):
  permission_classes = [IsAuthenticated, IsAdmin]

  def post(self, request, seller_id):
    seller = Seller.objects.filter(pk=seller_id).first()
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)

    token = str(request.data.get("token") or "").strip()
    if not token:
      return Response(
        {"detail": "Вставьте персональный токен WB"},
        status=status.HTTP_400_BAD_REQUEST,
      )

    seller.wb_api_token_encrypted = encrypt_token(token)
    seller.wb_enabled = True
    seller.save(update_fields=["wb_api_token_encrypted", "wb_enabled", "updated_at"])

    ping_ok = False
    ping_detail = ""
    try:
      sync_seller_warehouses(seller, user=request.user)
      ping_ok = True
    except WarehouseSyncError as exc:
      ping_detail = str(exc)

    payload = SellerManageSerializer(seller).data
    return Response({
      "success": True,
      "ping_ok": ping_ok,
      "detail": (
        "Токен WB сохранён. API отвечает, склады синхронизированы."
        if ping_ok
        else f"Токен сохранён, но проверка API не прошла: {ping_detail}"
      ),
      "seller": payload,
    })

  def delete(self, request, seller_id):
    seller = Seller.objects.filter(pk=seller_id).first()
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)
    seller.wb_api_token_encrypted = ""
    seller.save(update_fields=["wb_api_token_encrypted", "updated_at"])
    return Response(SellerManageSerializer(seller).data)


class SellerInviteView(APIView):
  permission_classes = [IsAuthenticated, IsAdmin]

  def post(self, request, seller_id):
    seller = Seller.objects.select_related("user_account").filter(pk=seller_id).first()
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)
    has_account = seller_has_user_account(seller)
    if has_account:
      return Response(
        {"detail": "Аккаунт уже создан. Новая ссылка не нужна."},
        status=status.HTTP_400_BAD_REQUEST,
      )
    invite = issue_seller_invite(seller)
    return Response(SellerInviteSerializer({
      "token": invite.token,
      "invite_path": _invite_path(request, str(invite.token)),
      "has_account": has_account,
      "company_name": seller.company_name,
    }).data)


class SellerInvitePreviewView(APIView):
  permission_classes = [AllowAny]

  def get(self, request, token):
    invite = get_invite_by_token(token)
    if not invite:
      return Response({"detail": "Ссылка недействительна"}, status=status.HTTP_404_NOT_FOUND)
    has_account = seller_has_user_account(invite.seller)
    return Response({
      "company_name": invite.seller.company_name,
      "has_account": has_account,
      "token": str(invite.token),
    })


class SellerRegisterView(APIView):
  permission_classes = [AllowAny]

  @transaction.atomic
  def post(self, request):
    serializer = SellerRegisterSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    invite = get_invite_by_token(serializer.validated_data["token"])
    if not invite:
      return Response({"detail": "Ссылка недействительна или уже использована"}, status=status.HTTP_400_BAD_REQUEST)
    if seller_has_user_account(invite.seller):
      return Response(
        {"detail": "Аккаунт для этого селлера уже создан. Войдите в CRM."},
        status=status.HTTP_400_BAD_REQUEST,
      )

    user = User.objects.create_user(
      username=serializer.validated_data["username"],
      password=serializer.validated_data["password"],
      email=serializer.validated_data.get("email") or "",
      role=User.Role.SELLER,
      seller=invite.seller,
    )
    deactivate_invite(invite)

    from apps.accounts.serializers import CustomTokenObtainPairSerializer

    refresh = CustomTokenObtainPairSerializer.get_token(user)
    return Response({
      "access": str(refresh.access_token),
      "refresh": str(refresh),
      "user": UserSerializer(user).data,
    }, status=status.HTTP_201_CREATED)


class SellerCabinetView(APIView):
  permission_classes = [IsAuthenticated, IsSeller]

  def get(self, request):
    seller = request.user.seller
    if not seller:
      return Response({"detail": "Селлер не привязан"}, status=status.HTTP_400_BAD_REQUEST)
    try:
      summary, items, wb_stages, weekly_shipments = build_seller_cabinet_payload(seller)
      summary_data = SellerCabinetSummarySerializer(summary).data
      wb_stages_data = SellerWbStageCountsSerializer(wb_stages).data
      weekly_data = SellerWeeklyShipmentsSerializer(weekly_shipments).data
      return Response({
        "seller": {"id": seller.id, "company_name": seller.company_name},
        "summary": summary_data,
        "wb_stages": wb_stages_data,
        "weekly_shipments": weekly_data,
        "items": SellerBarcodeAnalyticsSerializer(items, many=True).data,
        "meta": {
          "enabled_warehouses": get_enabled_warehouses_meta(seller),
          "source": "wb_statistics_api",
          "timezone": "Europe/Moscow",
        },
      })
    except SellerAnalyticsError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as exc:
      logger.exception("seller cabinet failed for seller %s", seller.id)
      return Response(
        {"detail": f"Ошибка загрузки кабинета: {exc}"},
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
      )


class SellerCabinetBarcodeView(APIView):
  permission_classes = [IsAuthenticated, IsSeller]

  def get(self, request, barcode):
    seller = request.user.seller
    if not seller:
      return Response({"detail": "Селлер не привязан"}, status=status.HTTP_400_BAD_REQUEST)
    try:
      detail = build_barcode_detail(seller, barcode)
    except SellerAnalyticsError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    if not detail:
      return Response(status=status.HTTP_404_NOT_FOUND)
    return Response(SellerBarcodeDetailSerializer(detail).data)


class AdminBillingDashboardView(APIView):
  permission_classes = [IsAuthenticated, IsAdmin]

  def get(self, request):
    try:
      payload = load_admin_billing_dashboard()
      return Response(AdminBillingDashboardSerializer(payload).data)
    except Exception as exc:
      logger.exception("admin billing dashboard failed")
      return Response(
        {"detail": f"Ошибка загрузки статистики: {exc}"},
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
      )
