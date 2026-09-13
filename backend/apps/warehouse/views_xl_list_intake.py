from django.http import HttpResponse
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsManager
from apps.warehouse.models import XlListSession
from apps.warehouse.services.xl_list_intake import (
  XlListIntakeError,
  add_line,
  build_excel_bytes,
  complete_session,
  create_session,
  delete_line,
  get_xl_list_session_for_user,
  scan_unit,
  serialize_session,
  update_line_quantity,
  xl_list_sessions_for_user,
)


def _session_or_404(user, session_id: int) -> XlListSession:
  return get_xl_list_session_for_user(user, session_id, prefetch_lines=True)


class XlListSessionListCreateView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def get(self, request):
    sessions = xl_list_sessions_for_user(request.user).order_by("-created_at")[:100]
    return Response([serialize_session(item) for item in sessions])

  def post(self, request):
    title = str(request.data.get("title") or "").strip()
    try:
      session = create_session(title=title, user=request.user)
    except XlListIntakeError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(serialize_session(session), status=status.HTTP_201_CREATED)


class XlListSessionDetailView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def get(self, request, session_id):
    session = _session_or_404(request.user, session_id)
    return Response(serialize_session(session))


class XlListScanView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, session_id):
    session = _session_or_404(request.user, session_id)
    barcode = str(request.data.get("barcode") or "")
    try:
      session, last_line = scan_unit(session, barcode)
    except XlListIntakeError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(serialize_session(session, last_line=last_line))


class XlListAddLineView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, session_id):
    session = _session_or_404(request.user, session_id)
    barcode = str(request.data.get("barcode") or "")
    try:
      quantity = int(request.data.get("quantity") or 0)
    except (TypeError, ValueError):
      quantity = 0
    try:
      session = add_line(session, barcode=barcode, quantity=quantity)
    except XlListIntakeError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(serialize_session(session))


class XlListLineUpdateView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, session_id):
    session = _session_or_404(request.user, session_id)
    barcode = str(request.data.get("barcode") or "")
    try:
      quantity = int(request.data.get("quantity") or 0)
    except (TypeError, ValueError):
      quantity = 0
    try:
      session = update_line_quantity(session, barcode=barcode, quantity=quantity)
    except XlListIntakeError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(serialize_session(session))


class XlListLineDeleteView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, session_id):
    session = _session_or_404(request.user, session_id)
    barcode = str(request.data.get("barcode") or "")
    try:
      session = delete_line(session, barcode=barcode)
    except XlListIntakeError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(serialize_session(session))


class XlListExcelView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def get(self, request, session_id):
    session = _session_or_404(request.user, session_id)
    try:
      payload = build_excel_bytes(session)
    except XlListIntakeError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    filename = f"barcodes-xl-list-{session.id}.xlsx"
    response = HttpResponse(
      payload,
      content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


class XlListCompleteView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, session_id):
    session = _session_or_404(request.user, session_id)
    try:
      session = complete_session(session, user=request.user)
    except XlListIntakeError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(serialize_session(session))
