from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.orders.services.sync_statuses import (
  DELIVERY_ORDER_MAX_AGE_DAYS,
  DELIVERY_WINDOW_DAYS,
  SYNC_VERSION,
)


class HealthView(APIView):
  permission_classes = [AllowAny]
  authentication_classes = []

  def get(self, request):
    return Response({
      "ok": True,
      "sync_version": SYNC_VERSION,
      "delivery_window_days": DELIVERY_WINDOW_DAYS,
      "delivery_max_age_days": DELIVERY_ORDER_MAX_AGE_DAYS,
    })
