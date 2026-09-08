from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsManager
from apps.accounts.tenant import get_intake_session_for_user, intake_sessions_for_user
from apps.integrations.marketplace import WB, parse_marketplace
from apps.warehouse.models import WbFactIntakeSession
from apps.warehouse.services.wb_fact_intake import (
  WbFactIntakeError,
  create_session,
  delete_session,
  finish_session,
  scan_barcode,
  serialize_session,
  set_line_quantity,
)


def _session_or_404(user, session_id: int) -> WbFactIntakeSession:
  return get_intake_session_for_user(user, WbFactIntakeSession, session_id)


def _require_wb(request):
  if parse_marketplace(request) != WB:
    raise WbFactIntakeError("Эта приёмка только для Wildberries")


class WbFactIntakeSessionListCreateView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def get(self, request):
    try:
      _require_wb(request)
    except WbFactIntakeError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    sessions = (
      intake_sessions_for_user(request.user, WbFactIntakeSession, marketplace=WB)
      .select_related("seller", "warehouse")
      .order_by("-created_at")[:100]
    )
    return Response([serialize_session(item, include_accepted=False) for item in sessions])

  def post(self, request):
    try:
      _require_wb(request)
      company_name = str(request.data.get("company_name") or "").strip()
      seller_id = request.data.get("seller_id")
      warehouse_id = request.data.get("warehouse_id")
      session = create_session(
        company_name=company_name,
        seller_id=int(seller_id) if seller_id else None,
        warehouse_id=int(warehouse_id) if warehouse_id else None,
        user=request.user,
        marketplace=WB,
      )
    except (WbFactIntakeError, ValueError, TypeError) as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(serialize_session(session), status=status.HTTP_201_CREATED)


class WbFactIntakeSessionDetailView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def get(self, request, session_id):
    session = _session_or_404(request.user, session_id)
    include_report = str(request.query_params.get("report") or "") in {"1", "true", "yes"}
    return Response(serialize_session(session, include_report=include_report))

  def delete(self, request, session_id):
    session = _session_or_404(request.user, session_id)
    try:
      result = delete_session(session, user=request.user)
    except WbFactIntakeError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)


class WbFactIntakeScanView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, session_id):
    session = _session_or_404(request.user, session_id)
    barcode = str(request.data.get("barcode") or "")
    scan_mode = str(request.data.get("scan_mode") or "piece")
    try:
      quantity = int(request.data.get("quantity") or 0)
    except (TypeError, ValueError):
      quantity = 0
    try:
      result = scan_barcode(
        session,
        barcode=barcode,
        quantity=quantity,
        scan_mode=scan_mode,
        user=request.user,
      )
    except WbFactIntakeError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)


class WbFactIntakeSetQtyView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, session_id):
    session = _session_or_404(request.user, session_id)
    barcode = str(request.data.get("barcode") or "")
    try:
      quantity = int(request.data.get("quantity"))
    except (TypeError, ValueError):
      return Response({"detail": "Укажите количество"}, status=status.HTTP_400_BAD_REQUEST)
    try:
      result = set_line_quantity(
        session,
        barcode=barcode,
        quantity=quantity,
        user=request.user,
      )
    except WbFactIntakeError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)


class WbFactIntakeReportView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def get(self, request, session_id):
    session = _session_or_404(request.user, session_id)
    return Response(serialize_session(session, include_report=True))


class WbFactIntakeFinishView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, session_id):
    session = _session_or_404(request.user, session_id)
    try:
      result = finish_session(session, user=request.user)
    except WbFactIntakeError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)
