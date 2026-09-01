from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsManager
from apps.accounts.tenant import get_seller_for_user, sellers_for_user
from apps.orders.services.off_crm_shipments import (
  OffCrmShipmentError,
  deduct_off_crm_shipment,
  off_crm_shipments_for_seller,
  off_crm_summary_by_seller,
  pending_off_crm_count,
  skip_off_crm_shipment,
)
from apps.sellers.models import Seller


def _seller_ids_for_user(user) -> list[int] | None:
  if user.role == "seller":
    if not user.seller_id:
      return []
    return [user.seller_id]
  return list(sellers_for_user(user).values_list("id", flat=True))


class OffCrmShipmentSummaryView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def get(self, request):
    seller_ids = _seller_ids_for_user(request.user)
    return Response({
      "pending_count": pending_off_crm_count(seller_ids=seller_ids),
      "sellers": off_crm_summary_by_seller(seller_ids=seller_ids),
    })


class OffCrmShipmentSellerDetailView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def get(self, request, seller_id: int):
    user = request.user
    if user.role == "seller" and user.seller_id != seller_id:
      return Response({"detail": "Нет доступа"}, status=status.HTTP_403_FORBIDDEN)

    seller = get_seller_for_user(user, seller_id)
    if not seller:
      return Response({"detail": "Селлер не найден"}, status=status.HTTP_404_NOT_FOUND)

    return Response({
      "seller_id": seller.id,
      "seller_name": seller.company_name,
      "items": off_crm_shipments_for_seller(seller),
    })


class OffCrmShipmentDeductView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, shipment_id: int):
    from apps.orders.models import OffCrmShipment

    shipment = OffCrmShipment.objects.filter(pk=shipment_id).select_related("seller").first()
    if not shipment:
      return Response({"detail": "Запись не найдена"}, status=status.HTTP_404_NOT_FOUND)

    user = request.user
    if user.role == "seller" and user.seller_id != shipment.seller_id:
      return Response({"detail": "Нет доступа"}, status=status.HTTP_403_FORBIDDEN)

    try:
      result = deduct_off_crm_shipment(shipment_id, user=user)
    except OffCrmShipmentError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    return Response(result)


class OffCrmShipmentSkipView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, shipment_id: int):
    from apps.orders.models import OffCrmShipment

    shipment = OffCrmShipment.objects.filter(pk=shipment_id).first()
    if not shipment:
      return Response({"detail": "Запись не найдена"}, status=status.HTTP_404_NOT_FOUND)

    user = request.user
    if user.role == "seller" and user.seller_id != shipment.seller_id:
      return Response({"detail": "Нет доступа"}, status=status.HTTP_403_FORBIDDEN)

    try:
      result = skip_off_crm_shipment(shipment_id, user=user)
    except OffCrmShipmentError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    return Response(result)
