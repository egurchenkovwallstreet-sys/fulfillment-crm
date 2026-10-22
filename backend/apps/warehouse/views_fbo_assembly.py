from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsManager
from apps.accounts.tenant import get_seller_for_user, intake_sessions_for_user
from apps.integrations.marketplace import WB
from apps.warehouse.models import FboAssemblySession
from apps.warehouse.services.fbo_assembly import (
  FboAssemblyError,
  build_excel_bytes,
  close_box,
  complete_session,
  create_box,
  create_session,
  pause_session,
  resume_session,
  scan_barcode,
  serialize_box_label,
  serialize_session,
)


def _session_or_404(user, session_id: int) -> FboAssemblySession:
  qs = (
    intake_sessions_for_user(user, FboAssemblySession, marketplace=WB)
    .select_related("seller")
    .prefetch_related("boxes__lines")
  )
  return get_object_or_404(qs, pk=session_id)


class FboAssemblySessionListCreateView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def get(self, request):
    sessions = (
      intake_sessions_for_user(request.user, FboAssemblySession, marketplace=WB)
      .select_related("seller")
      .prefetch_related("boxes__lines")
      .order_by("-created_at")[:100]
    )
    return Response([serialize_session(item) for item in sessions])

  def post(self, request):
    seller_id = request.data.get("seller_id")
    if not seller_id:
      return Response({"detail": "Укажите seller_id"}, status=status.HTTP_400_BAD_REQUEST)
    seller = get_seller_for_user(request.user, seller_id, active_only=True)
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)
    try:
      session = create_session(seller=seller, user=request.user)
    except FboAssemblyError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    session = _session_or_404(request.user, session.id)
    return Response(serialize_session(session), status=status.HTTP_201_CREATED)


class FboAssemblySessionDetailView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def get(self, request, session_id):
    session = _session_or_404(request.user, session_id)
    return Response(serialize_session(session))


class FboAssemblyPauseView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, session_id):
    try:
      session = _session_or_404(request.user, session_id)
    except FboAssemblySession.DoesNotExist:
      return Response(status=status.HTTP_404_NOT_FOUND)
    try:
      pause_session(session)
    except FboAssemblyError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    session = _session_or_404(request.user, session_id)
    return Response(serialize_session(session))


class FboAssemblyResumeView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, session_id):
    try:
      session = _session_or_404(request.user, session_id)
    except FboAssemblySession.DoesNotExist:
      return Response(status=status.HTTP_404_NOT_FOUND)
    try:
      resume_session(session)
    except FboAssemblyError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    session = _session_or_404(request.user, session_id)
    return Response(serialize_session(session))


class FboAssemblyCompleteView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, session_id):
    try:
      session = _session_or_404(request.user, session_id)
    except FboAssemblySession.DoesNotExist:
      return Response(status=status.HTTP_404_NOT_FOUND)
    try:
      complete_session(session, user=request.user)
    except FboAssemblyError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    session = _session_or_404(request.user, session_id)
    return Response(serialize_session(session))


class FboAssemblyCreateBoxView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, session_id):
    try:
      session = _session_or_404(request.user, session_id)
    except FboAssemblySession.DoesNotExist:
      return Response(status=status.HTTP_404_NOT_FOUND)
    try:
      box = create_box(session, box_number=str(request.data.get("box_number") or ""))
    except FboAssemblyError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    session = _session_or_404(request.user, session_id)
    payload = serialize_session(session)
    payload["created_box_id"] = box.id
    return Response(payload)


class FboAssemblyCloseBoxView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, session_id, box_id):
    try:
      session = _session_or_404(request.user, session_id)
    except FboAssemblySession.DoesNotExist:
      return Response(status=status.HTTP_404_NOT_FOUND)
    try:
      box = close_box(session, box_id=box_id)
    except FboAssemblyError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    session = _session_or_404(request.user, session_id)
    payload = serialize_session(session)
    payload["closed_box_label"] = serialize_box_label(box)
    return Response(payload)


class FboAssemblyScanView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, session_id, box_id):
    try:
      session = _session_or_404(request.user, session_id)
    except FboAssemblySession.DoesNotExist:
      return Response(status=status.HTTP_404_NOT_FOUND)
    barcode = str(request.data.get("barcode") or "").strip()
    try:
      line, deducted = scan_barcode(
        session,
        box_id=box_id,
        barcode=barcode,
        user=request.user,
      )
    except FboAssemblyError as exc:
      body = {"detail": str(exc)}
      if exc.code:
        body["code"] = exc.code
      code = status.HTTP_400_BAD_REQUEST
      if exc.code == "wrong_seller":
        code = status.HTTP_404_NOT_FOUND
      return Response(body, status=code)
    session = _session_or_404(request.user, session_id)
    payload = serialize_session(session)
    payload["last_scan"] = {
      "barcode": line.barcode,
      "quantity_in_box": line.quantity,
      "stock_deducted": deducted,
    }
    return Response(payload)


class FboAssemblyExcelView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def get(self, request, session_id):
    try:
      session = _session_or_404(request.user, session_id)
    except FboAssemblySession.DoesNotExist:
      return Response(status=status.HTTP_404_NOT_FOUND)
    try:
      content = build_excel_bytes(session)
    except FboAssemblyError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    filename = f"fbo-assembly-{session.id}.xlsx"
    response = HttpResponse(
      content,
      content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
