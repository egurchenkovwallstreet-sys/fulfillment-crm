from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsManager
from apps.integrations.marketplace import parse_marketplace
from apps.sellers.models import Seller
from apps.warehouse.models import XlIntakeSession
from apps.warehouse.services.xl_intake import (
  XlIntakeError,
  apply_after_wb,
  build_excel_bytes,
  complete_session,
  create_session,
  create_session_for_seller,
  delete_line,
  last_scanned_line,
  save_session,
  scan_unit,
  serialize_session,
  update_line_quantity,
)


def _session_or_404(session_id: int) -> XlIntakeSession:
  return get_object_or_404(
    XlIntakeSession.objects.select_related("seller").prefetch_related("lines"),
    pk=session_id,
  )


class XlIntakeSessionListCreateView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def get(self, request):
    marketplace = parse_marketplace(request)
    sessions = (
      XlIntakeSession.objects.filter(marketplace=marketplace)
      .select_related("seller")
      .prefetch_related("lines")
      .order_by("-created_at")[:100]
    )
    return Response([serialize_session(item) for item in sessions])

  def post(self, request):
    company_name = str(request.data.get("company_name") or "").strip()
    seller_id = request.data.get("seller_id")
    marketplace = parse_marketplace(request)
    try:
      if seller_id:
        seller = get_object_or_404(Seller, pk=seller_id, is_active=True)
        session = create_session_for_seller(
          seller=seller,
          user=request.user,
          marketplace=marketplace,
        )
      else:
        session = create_session(
          company_name=company_name,
          user=request.user,
          marketplace=marketplace,
        )
    except XlIntakeError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(serialize_session(session), status=status.HTTP_201_CREATED)


class XlIntakeSessionDetailView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def get(self, request, session_id):
    session = _session_or_404(session_id)
    return Response(serialize_session(session))


class XlIntakeScanView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, session_id):
    session = _session_or_404(session_id)
    barcode = str(request.data.get("barcode") or "")
    try:
      session = scan_unit(session, barcode)
    except XlIntakeError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(serialize_session(session, last_line=last_scanned_line(session)))


class XlIntakeLineUpdateView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, session_id):
    session = _session_or_404(session_id)
    barcode = str(request.data.get("barcode") or "")
    try:
      quantity = int(request.data.get("quantity") or 0)
    except (TypeError, ValueError):
      quantity = 0
    try:
      session = update_line_quantity(session, barcode=barcode, quantity=quantity)
    except XlIntakeError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(serialize_session(session))


class XlIntakeLineDeleteView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, session_id):
    session = _session_or_404(session_id)
    barcode = str(request.data.get("barcode") or "")
    try:
      session = delete_line(session, barcode=barcode)
    except XlIntakeError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(serialize_session(session))


class XlIntakeSaveView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, session_id):
    session = _session_or_404(session_id)
    try:
      session = save_session(session, user=request.user)
    except XlIntakeError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(serialize_session(session))


class XlIntakeExcelView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def get(self, request, session_id):
    session = _session_or_404(session_id)
    try:
      payload = build_excel_bytes(session)
    except XlIntakeError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    filename = f"priemka-xl-{session.id}.xlsx"
    response = HttpResponse(
      payload,
      content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


class XlIntakeConnectWbView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, session_id):
    session = _session_or_404(session_id)
    token = str(request.data.get("token") or "")
    try:
      result = apply_after_wb(session, token=token, user=request.user)
    except XlIntakeError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)


class XlIntakeCompleteView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, session_id):
    session = _session_or_404(session_id)
    try:
      session = complete_session(session, user=request.user)
    except XlIntakeError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(serialize_session(session))
