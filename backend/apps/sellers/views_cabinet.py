import logging

from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsAdmin, IsSeller
from apps.accounts.serializers import UserSerializer
from apps.accounts.tenant import fulfillment_for_staff_user, get_seller_for_user, sellers_for_user
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
from apps.integrations.marketplace import parse_marketplace, seller_allows_marketplace
from apps.sellers.services.invite import (
  deactivate_invite,
  ensure_seller_invite,
  get_invite_by_token,
  issue_seller_invite,
)
from apps.sellers.services.seller_manage import (
  SellerManageError,
  apply_ozon_keys,
  apply_wb_token,
  clear_wb_token,
  delete_seller,
)
from apps.sellers.services.seller_analytics import build_barcode_detail, build_seller_cabinet_payload
from apps.sellers.services.seller_billing_stats import load_admin_billing_dashboard
from apps.sellers.services.wb_order_stats import SellerAnalyticsError
from apps.sellers.utils import seller_has_user_account, seller_username

User = get_user_model()
logger = logging.getLogger(__name__)


def _invite_path(request, token: str) -> str:
  return f"{request.scheme}://{request.get_host()}/register/{token}"


def _seller_queryset(user):
  return sellers_for_user(user).select_related("user_account").select_related("invite")


class SellerManageListCreateView(APIView):
  permission_classes = [IsAuthenticated, IsAdmin]

  def get(self, request):
    sellers = _seller_queryset(request.user).order_by("company_name")
    for seller in sellers:
      ensure_seller_invite(seller)
    sellers = _seller_queryset(request.user).order_by("company_name")
    return Response(SellerManageSerializer(sellers, many=True).data)

  def post(self, request):
    serializer = SellerCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    fulfillment = fulfillment_for_staff_user(request.user)
    if not fulfillment:
      return Response({"detail": "Фулфилмент не определён"}, status=status.HTTP_400_BAD_REQUEST)

    data = serializer.validated_data
    wb_token = str(data.pop("wb_token", "") or "").strip()
    ozon_client_id = str(data.pop("ozon_client_id", "") or "").strip()
    ozon_api_key = str(data.pop("ozon_api_key", "") or "").strip()

    seller = serializer.save(fulfillment=fulfillment)
    invite = ensure_seller_invite(seller)

    token_messages: list[str] = []
    if wb_token and seller.wb_enabled:
      try:
        _, msg = apply_wb_token(seller, wb_token, user=request.user)
        token_messages.append(msg)
      except SellerManageError as exc:
        token_messages.append(str(exc))
    if ozon_client_id and ozon_api_key and seller.ozon_enabled:
      try:
        _, msg = apply_ozon_keys(seller, ozon_client_id, ozon_api_key)
        token_messages.append(msg)
      except SellerManageError as exc:
        token_messages.append(str(exc))

    seller.refresh_from_db()
    payload = SellerManageSerializer(seller).data
    payload["invite_url"] = _invite_path(request, invite.token)
    if token_messages:
      payload["token_messages"] = token_messages
    return Response(payload, status=status.HTTP_201_CREATED)


class SellerManageDetailView(APIView):
  permission_classes = [IsAuthenticated, IsAdmin]

  def patch(self, request, seller_id):
    seller = get_seller_for_user(request.user, seller_id)
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)
    serializer = SellerUpdateSerializer(seller, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    seller.refresh_from_db()
    return Response(SellerManageSerializer(seller).data)

  def delete(self, request, seller_id):
    seller = get_seller_for_user(request.user, seller_id)
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)
    name = seller.company_name
    try:
      delete_seller(seller)
    except SellerManageError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response({"success": True, "detail": f"Селлер «{name}» удалён"})


class SellerWbTokenView(APIView):
  permission_classes = [IsAuthenticated, IsAdmin]

  def post(self, request, seller_id):
    seller = get_seller_for_user(request.user, seller_id)
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)

    token = str(request.data.get("token") or "").strip()
    try:
      ping_ok, detail = apply_wb_token(seller, token, user=request.user)
    except SellerManageError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    seller.refresh_from_db()
    return Response({
      "success": True,
      "ping_ok": ping_ok,
      "detail": detail,
      "seller": SellerManageSerializer(seller).data,
    })

  def delete(self, request, seller_id):
    seller = get_seller_for_user(request.user, seller_id)
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)
    clear_wb_token(seller)
    seller.refresh_from_db()
    return Response(SellerManageSerializer(seller).data)


class SellerInviteView(APIView):
  permission_classes = [IsAuthenticated, IsAdmin]

  def post(self, request, seller_id):
    seller = get_seller_for_user(request.user, seller_id)
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
    marketplace = parse_marketplace(request)
    if not seller_allows_marketplace(seller, marketplace):
      return Response({"detail": "Маркетплейс недоступен для этого селлера"}, status=status.HTTP_400_BAD_REQUEST)
    try:
      summary, items, stages, weekly_shipments, meta = build_seller_cabinet_payload(
        seller,
        marketplace=marketplace,
      )
      summary_data = SellerCabinetSummarySerializer(summary).data
      stages_data = SellerWbStageCountsSerializer(stages).data
      weekly_data = SellerWeeklyShipmentsSerializer(weekly_shipments).data
      return Response({
        "seller": {"id": seller.id, "company_name": seller.company_name},
        "marketplace": marketplace,
        "summary": summary_data,
        "stages": stages_data,
        "wb_stages": stages_data,
        "weekly_shipments": weekly_data,
        "items": SellerBarcodeAnalyticsSerializer(items, many=True).data,
        "meta": meta,
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
    marketplace = parse_marketplace(request)
    if not seller_allows_marketplace(seller, marketplace):
      return Response({"detail": "Маркетплейс недоступен для этого селлера"}, status=status.HTTP_400_BAD_REQUEST)
    try:
      detail = build_barcode_detail(seller, barcode, marketplace=marketplace)
    except SellerAnalyticsError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    if not detail:
      return Response(status=status.HTTP_404_NOT_FOUND)
    return Response(SellerBarcodeDetailSerializer(detail).data)


class AdminBillingDashboardView(APIView):
  permission_classes = [IsAuthenticated, IsAdmin]

  def get(self, request):
    try:
      marketplace = parse_marketplace(request)
      payload = load_admin_billing_dashboard(
        fulfillment=fulfillment_for_staff_user(request.user),
        marketplace=marketplace,
      )
      return Response(AdminBillingDashboardSerializer(payload).data)
    except Exception as exc:
      logger.exception("admin billing dashboard failed")
      return Response(
        {"detail": f"Ошибка загрузки статистики: {exc}"},
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
      )
