from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.orders.services.sync_statuses import SYNC_VERSION


class HealthView(APIView):
  permission_classes = [AllowAny]
  authentication_classes = []

  def get(self, request):
    return Response({
      "ok": True,
      "sync_version": SYNC_VERSION,
    })
