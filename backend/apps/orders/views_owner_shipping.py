from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsAdmin
from apps.accounts.tenant import get_seller_for_user
from apps.orders.services.supply_flow import (
  SupplyFlowError,
  fetch_fulfillment_shipping_points_catalog,
)


class OwnerShippingPointsView(APIView):
  """Справочник пунктов отгрузки WB для владельца — без передачи заказов в доставку."""
  permission_classes = [IsAuthenticated, IsAdmin]

  def get(self, request):
    refresh = (request.query_params.get("refresh") or "").strip() in ("1", "true", "yes")
    seller_id_raw = (request.query_params.get("seller_id") or "").strip()
    seller = None
    if seller_id_raw.isdigit():
      seller = get_seller_for_user(request.user, int(seller_id_raw), active_only=True)

    try:
      payload = fetch_fulfillment_shipping_points_catalog(
        request.user,
        seller=seller,
        force_refresh=refresh,
      )
    except SupplyFlowError as exc:
      return Response({"detail": str(exc), "code": exc.code}, status=status.HTTP_400_BAD_REQUEST)
    return Response(payload)
