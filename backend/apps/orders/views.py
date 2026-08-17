from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsManager
from apps.sellers.models import Seller

from .models import Order, PickList
from .serializers import (
  OrderSerializer,
  OrderSyncSerializer,
  PickListBriefSerializer,
  PickListGenerateSerializer,
  PickListSerializer,
)
from .services.pick_list import PickListError, generate_pick_list
from .services.sync_orders import SyncError, sync_all_active_sellers, sync_orders_for_seller


def _orders_queryset_for_user(user):
  qs = Order.objects.select_related("seller", "product", "product__cell")
  if user.role == "seller":
    if not user.seller_id:
      return qs.none()
    return qs.filter(seller_id=user.seller_id)
  return qs


def _pick_lists_queryset_for_user(user):
  qs = PickList.objects.select_related("seller").prefetch_related("items__cell", "items__product")
  if user.role == "seller":
    if not user.seller_id:
      return qs.none()
    return qs.filter(seller_id=user.seller_id)
  return qs


class OrderListView(APIView):
  permission_classes = [IsAuthenticated]

  def get(self, request):
    qs = _orders_queryset_for_user(request.user)

    seller_id = request.query_params.get("seller_id")
    order_status = request.query_params.get("status")

    if seller_id and request.user.role != "seller":
      qs = qs.filter(seller_id=seller_id)
    if order_status:
      qs = qs.filter(status=order_status)

    qs = qs.order_by("-created_at")[:200]
    return Response(OrderSerializer(qs, many=True).data)


class OrderStatsView(APIView):
  permission_classes = [IsAuthenticated]

  def get(self, request):
    user = request.user
    today = timezone.localdate()
    orders_qs = _orders_queryset_for_user(user)

    orders_today = orders_qs.filter(created_at__date=today).count()
    in_picking = orders_qs.filter(
      status__in=[Order.Status.IN_PICKING, Order.Status.ASSEMBLED]
    ).count()
    new_orders = orders_qs.filter(status=Order.Status.NEW).count()

    data = {
      "orders_today": orders_today,
      "in_picking": in_picking,
      "new_orders": new_orders,
    }

    if user.role == "admin":
      data["sellers_count"] = Seller.objects.filter(is_active=True).count()
    elif user.role == "manager":
      data["sellers_count"] = Seller.objects.filter(is_active=True).count()

    from apps.warehouse.models import Product

    products_qs = Product.objects.all()
    if user.role == "seller" and user.seller_id:
      products_qs = products_qs.filter(seller_id=user.seller_id)
    data["sku_count"] = products_qs.count()

    return Response(data)


class OrderSyncView(APIView):
  permission_classes = [IsAuthenticated]

  def post(self, request):
    user = request.user
    serializer = OrderSyncSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    seller_id = serializer.validated_data.get("seller_id")

    if user.role == "seller":
      if not user.seller_id:
        return Response(
          {"detail": "У пользователя не привязан селлер"},
          status=status.HTTP_400_BAD_REQUEST,
        )
      try:
        result = sync_orders_for_seller(user.seller, user=user)
      except SyncError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
      return Response({"success": True, **result})

    if not (user.role in ("admin", "manager")):
      return Response(status=status.HTTP_403_FORBIDDEN)

    if seller_id:
      seller = Seller.objects.get(pk=seller_id, is_active=True)
      try:
        result = sync_orders_for_seller(seller, user=user)
      except SyncError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
      return Response({"success": True, **result})

    payload = sync_all_active_sellers(user=user)
    return Response({"success": True, **payload})


class PickListListView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def get(self, request):
    qs = _pick_lists_queryset_for_user(request.user)
    seller_id = request.query_params.get("seller_id")
    if seller_id:
      qs = qs.filter(seller_id=seller_id)
    qs = qs.order_by("-created_at")[:50]
    return Response(PickListBriefSerializer(qs, many=True).data)


class PickListDetailView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def get(self, request, pk):
    qs = _pick_lists_queryset_for_user(request.user)
    pick_list = qs.filter(pk=pk).first()
    if not pick_list:
      return Response(status=status.HTTP_404_NOT_FOUND)
    return Response(PickListSerializer(pick_list).data)


class PickListGenerateView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request):
    serializer = PickListGenerateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    seller = Seller.objects.get(pk=serializer.validated_data["seller_id"], is_active=True)

    try:
      pick_list = generate_pick_list(seller, user=request.user)
    except PickListError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    pick_list = _pick_lists_queryset_for_user(request.user).get(pk=pick_list.pk)
    return Response(
      PickListSerializer(pick_list).data,
      status=status.HTTP_201_CREATED,
    )
