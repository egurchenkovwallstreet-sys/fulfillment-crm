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
  SellerBarcodeAnalyticsSerializer,
  SellerBarcodeDetailSerializer,
  SellerCabinetSummarySerializer,
  SellerCreateSerializer,
  SellerInviteSerializer,
  SellerManageSerializer,
  SellerRegisterSerializer,
)
from apps.sellers.services.invite import (
  deactivate_invite,
  ensure_seller_invite,
  get_invite_by_token,
  issue_seller_invite,
)
from apps.sellers.services.seller_analytics import (
  build_barcode_analytics,
  build_barcode_detail,
  build_seller_summary,
)

User = get_user_model()


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


class SellerInviteView(APIView):
  permission_classes = [IsAuthenticated, IsAdmin]

  def post(self, request, seller_id):
    seller = Seller.objects.select_related("user_account").filter(pk=seller_id).first()
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)
    has_account = hasattr(seller, "user_account") and seller.user_account_id is not None
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
    has_account = hasattr(invite.seller, "user_account") and invite.seller.user_account_id is not None
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
    if hasattr(invite.seller, "user_account") and invite.seller.user_account_id:
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
    return Response({
      "seller": {"id": seller.id, "company_name": seller.company_name},
      "summary": SellerCabinetSummarySerializer(build_seller_summary(seller)).data,
      "items": SellerBarcodeAnalyticsSerializer(build_barcode_analytics(seller), many=True).data,
    })


class SellerCabinetBarcodeView(APIView):
  permission_classes = [IsAuthenticated, IsSeller]

  def get(self, request, barcode):
    seller = request.user.seller
    if not seller:
      return Response({"detail": "Селлер не привязан"}, status=status.HTTP_400_BAD_REQUEST)
    detail = build_barcode_detail(seller, barcode)
    if not detail:
      return Response(status=status.HTTP_404_NOT_FOUND)
    return Response(SellerBarcodeDetailSerializer(detail).data)
