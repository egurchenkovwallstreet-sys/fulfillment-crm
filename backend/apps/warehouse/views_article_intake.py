from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsManager
from apps.integrations.marketplace import parse_marketplace
from apps.sellers.models import Seller
from apps.warehouse.models import ArticleIntakeSession
from apps.warehouse.services.article_intake import (
  ArticleIntakeError,
  complete_session,
  confirm_group,
  create_session,
  push_to_marketplace,
  scan_barcode,
  serialize_session,
)


def _session_or_404(session_id: int) -> ArticleIntakeSession:
  return get_object_or_404(
    ArticleIntakeSession.objects.select_related("seller"),
    pk=session_id,
  )


class ArticleIntakeSessionListCreateView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def get(self, request):
    marketplace = parse_marketplace(request)
    sessions = (
      ArticleIntakeSession.objects.filter(marketplace=marketplace)
      .select_related("seller")
      .order_by("-created_at")[:100]
    )
    return Response([serialize_session(item) for item in sessions])

  def post(self, request):
    marketplace = parse_marketplace(request)
    company_name = str(request.data.get("company_name") or "").strip()
    seller_id = request.data.get("seller_id")
    try:
      session = create_session(
        company_name=company_name,
        seller_id=int(seller_id) if seller_id else None,
        user=request.user,
        marketplace=marketplace,
      )
    except (ArticleIntakeError, ValueError) as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(serialize_session(session), status=status.HTTP_201_CREATED)


class ArticleIntakeSessionDetailView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def get(self, request, session_id):
    session = _session_or_404(session_id)
    return Response(serialize_session(session))


class ArticleIntakeScanView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, session_id):
    session = _session_or_404(session_id)
    barcode = str(request.data.get("barcode") or "")
    try:
      quantity = int(request.data.get("quantity") or 0)
    except (TypeError, ValueError):
      quantity = 0
    try:
      result = scan_barcode(session, barcode=barcode, quantity=quantity, user=request.user)
    except ArticleIntakeError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)


class ArticleIntakeConfirmGroupView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, session_id):
    session = _session_or_404(session_id)
    scanned_barcode = str(request.data.get("scanned_barcode") or "")
    try:
      scanned_quantity = int(request.data.get("scanned_quantity") or 0)
    except (TypeError, ValueError):
      scanned_quantity = 0
    items = request.data.get("items") or []
    if not isinstance(items, list):
      items = []
    try:
      result = confirm_group(
        session,
        scanned_barcode=scanned_barcode,
        scanned_quantity=scanned_quantity,
        items=items,
        user=request.user,
      )
    except ArticleIntakeError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)


class ArticleIntakePushView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, session_id):
    session = _session_or_404(session_id)
    try:
      warehouse_id = int(request.data.get("warehouse_id") or 0)
    except (TypeError, ValueError):
      warehouse_id = 0
    mode = str(request.data.get("mode") or "replace")
    try:
      result = push_to_marketplace(
        session,
        warehouse_id=warehouse_id,
        mode=mode,
        user=request.user,
      )
    except ArticleIntakeError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)


class ArticleIntakeCompleteView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, session_id):
    session = _session_or_404(session_id)
    try:
      session = complete_session(session, user=request.user)
    except ArticleIntakeError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(serialize_session(session))
