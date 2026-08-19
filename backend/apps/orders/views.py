from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsManager
from apps.sellers.models import Seller

from apps.orders.services.wb_status import WB_STAGE_FILTERS, WB_SUPPLIER_NEW

from .models import Order, PickList, Supply
from .serializers import (
  OrderAssemblySerializer,
  OrderPrintSerializer,
  OrderSerializer,
  OrderSyncSerializer,
  PickListBriefSerializer,
  PickListGenerateSerializer,
  PickListSerializer,
  ScanPrintSerializer,
  SellerAssemblyCountersSerializer,
)
from .services.assembly import (
  AssemblyError,
  get_seller_stage_counts,
  scan_and_print,
  start_assembly,
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
    new_orders = orders_qs.filter(wb_supplier_status=WB_SUPPLIER_NEW).count()
    in_assembly = orders_qs.filter(wb_supplier_status="confirm").count()
    in_delivery = orders_qs.filter(wb_supplier_status="complete").count()

    data = {
      "orders_today": orders_today,
      "in_picking": in_picking,
      "new_orders": new_orders,
      "in_assembly": in_assembly,
      "in_delivery": in_delivery,
    }

    if user.role in ("admin", "manager"):
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

    if user.role not in ("admin", "manager"):
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


class AssemblySellerListView(APIView):
  """Список селлеров со счётчиками заказов по стадиям."""
  permission_classes = [IsAuthenticated, IsManager]

  def get(self, request):
    sellers = Seller.objects.filter(is_active=True).order_by("company_name")
    payload = []
    for seller in sellers:
      counts = get_seller_stage_counts(seller)
      total_active = counts["new"] + counts["in_picking"] + counts["in_delivery"]
      payload.append({
        "id": seller.id,
        "company_name": seller.company_name,
        **counts,
        "total_active": total_active,
      })
    return Response(SellerAssemblyCountersSerializer(payload, many=True).data)


class AssemblySellerDetailView(APIView):
  """Кабинет сборки конкретного селлера."""
  permission_classes = [IsAuthenticated, IsManager]

  def get(self, request, seller_id):
    seller = Seller.objects.filter(pk=seller_id, is_active=True).first()
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)

    counts = get_seller_stage_counts(seller)
    stage = request.query_params.get("stage", "")
    orders_qs = Order.objects.filter(seller=seller).select_related("product", "product__cell")
    if stage in WB_STAGE_FILTERS:
      orders_qs = orders_qs.filter(**WB_STAGE_FILTERS[stage])
    elif stage:
      orders_qs = orders_qs.filter(status=stage)
    else:
      orders_qs = orders_qs.filter(
        wb_supplier_status__in=[WB_SUPPLIER_NEW, "confirm", "complete"]
      ).exclude(status=Order.Status.CANCELLED)

    orders = orders_qs.order_by("-created_at")[:300]

    active_pick_list = (
      PickList.objects.filter(seller=seller, is_completed=False)
      .prefetch_related("items__cell", "items__product")
      .order_by("-created_at")
      .first()
    )

    supplies_forming = Supply.objects.filter(
      seller=seller,
      status=Supply.Status.FORMING,
    ).count()

    return Response({
      "seller": {"id": seller.id, "company_name": seller.company_name},
      "counts": counts,
      "supplies_forming": supplies_forming,
      "orders": OrderAssemblySerializer(orders, many=True).data,
      "active_pick_list": (
        PickListSerializer(active_pick_list).data if active_pick_list else None
      ),
    })


class AssemblyStartView(APIView):
  """Начать сборку: лист подбора + стикеры WB."""
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, seller_id):
    seller = Seller.objects.filter(pk=seller_id, is_active=True).first()
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)

    try:
      result = start_assembly(seller, user=request.user)
    except PickListError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    pick_list = PickList.objects.filter(pk=result["pick_list_id"]).first()
    return Response({
      "success": True,
      **result,
      "pick_list": PickListSerializer(pick_list).data if pick_list else None,
    }, status=status.HTTP_201_CREATED)


class AssemblyScanPrintView(APIView):
  """Скан баркода → данные стикера для печати."""
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, seller_id):
    seller = Seller.objects.filter(pk=seller_id, is_active=True).first()
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)

    serializer = ScanPrintSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    try:
      order = scan_and_print(
        seller,
        serializer.validated_data["barcode"],
        user=request.user,
      )
    except AssemblyError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    return Response({
      "success": True,
      "order": OrderPrintSerializer(order).data,
    })
