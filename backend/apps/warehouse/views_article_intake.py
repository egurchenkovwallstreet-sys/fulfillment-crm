from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsManager
from apps.accounts.tenant import get_intake_session_for_user, intake_sessions_for_user
from apps.integrations.marketplace import parse_marketplace
from apps.warehouse.models import ArticleIntakeSession
from apps.warehouse.services.article_intake import (
  ArticleIntakeError,
  complete_session,
  confirm_group,
  create_session,
  delete_intake_product,
  increment_product,
  push_to_marketplace,
  save_group_quantities,
  scan_barcode,
  serialize_session,
)


def _session_or_404(user, session_id: int) -> ArticleIntakeSession:
  return get_intake_session_for_user(user, ArticleIntakeSession, session_id)


class ArticleIntakeSessionListCreateView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def get(self, request):
    marketplace = parse_marketplace(request)
    sessions = (
      intake_sessions_for_user(request.user, ArticleIntakeSession, marketplace=marketplace)
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
    session = _session_or_404(request.user, session_id)
    return Response(serialize_session(session))


class ArticleIntakeScanView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, session_id):
    session = _session_or_404(request.user, session_id)
    barcode = str(request.data.get("barcode") or "")
    scan_mode = str(request.data.get("scan_mode") or "lookup")
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
    except ArticleIntakeError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)


class ArticleIntakeIncrementView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, session_id):
    session = _session_or_404(request.user, session_id)
    barcode = str(request.data.get("barcode") or "")
    try:
      result = increment_product(session, barcode=barcode, user=request.user)
    except ArticleIntakeError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)


class ArticleIntakeConfirmGroupView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, session_id):
    session = _session_or_404(request.user, session_id)
    scanned_barcode = str(request.data.get("scanned_barcode") or "")
    items = request.data.get("items") or []
    if not isinstance(items, list):
      items = []
    try:
      result = confirm_group(
        session,
        scanned_barcode=scanned_barcode,
        scanned_quantity=0,
        items=items,
        user=request.user,
      )
    except ArticleIntakeError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)


class ArticleIntakeSaveQuantitiesView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, session_id):
    session = _session_or_404(request.user, session_id)
    group_key = str(request.data.get("group_key") or "")
    items = request.data.get("items") or []
    if not isinstance(items, list):
      items = []
    try:
      result = save_group_quantities(
        session,
        group_key=group_key,
        items=items,
        user=request.user,
      )
    except ArticleIntakeError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)


class ArticleIntakeDeleteProductView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, session_id):
    session = _session_or_404(request.user, session_id)
    try:
      product_id = int(request.data.get("product_id") or 0)
    except (TypeError, ValueError):
      product_id = 0
    try:
      result = delete_intake_product(session, product_id=product_id, user=request.user)
    except ArticleIntakeError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)


class ArticleIntakePushView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, session_id):
    session = _session_or_404(request.user, session_id)
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
    session = _session_or_404(request.user, session_id)
    try:
      session = complete_session(session, user=request.user)
    except ArticleIntakeError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(serialize_session(session))
