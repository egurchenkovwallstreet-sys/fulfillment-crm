from django.db.models import Max, Sum
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsManager
from apps.sellers.models import Seller, SellerWarehouse
from apps.sellers.serializers import SellerWarehouseSerializer

from apps.orders.services.wb_status import WB_STAGE_QUERIES, WB_SUPPLIER_NEW, wb_active_q, wb_in_delivery_q
from apps.sellers.services.warehouse_filter import filter_orders_queryset

from .models import Order, PickList, Supply
from .serializers import (
  BindMarkingSerializer,
  OrderAssemblySerializer,
  OrderPrintSerializer,
  OrderSerializer,
  OrderSyncSerializer,
  PickListBriefSerializer,
  PickListGenerateSerializer,
  PickListSerializer,
  ReplaceOrderSerializer,
  ScanPrintSerializer,
  SellerAssemblyCountersSerializer,
)
from .services.assembly import (
  AssemblyError,
  bind_marking_and_print,
  get_seller_stage_counts,
  replace_order_item,
  scan_order_barcode,
  start_assembly,
)
from .services.pick_list import PickListError, generate_pick_list
from .services.sync_orders import SyncError, sync_all_active_sellers, sync_orders_for_seller


def _dashboard_stats_from_counts(counts: dict) -> dict:
  return {
    "new_orders": int(counts.get("new", 0) or 0),
    "in_assembly": int(counts.get("in_picking", 0) or 0),
    "in_delivery": int(counts.get("in_delivery", 0) or 0),
  }


def _aggregate_sync_dashboard_stats(results: list[dict]) -> dict:
  totals = {"new": 0, "in_picking": 0, "in_delivery": 0}
  for item in results:
    src = item.get("live_counts") or item.get("wb_counts") or {}
    totals["new"] += int(src.get("new", 0) or 0)
    totals["in_picking"] += int(src.get("in_picking", 0) or 0)
    totals["in_delivery"] += int(src.get("in_delivery", 0) or 0)
  return _dashboard_stats_from_counts(totals)


def _orders_queryset_for_user(user):
  qs = Order.objects.select_related("seller", "product", "product__cell")
  if user.role == "seller":
    if not user.seller_id:
      return qs.none()
    qs = qs.filter(seller_id=user.seller_id)
    return filter_orders_queryset(qs, seller=Seller.objects.filter(pk=user.seller_id).first())
  return filter_orders_queryset(qs)


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

    from apps.warehouse.models import Product

    counts_synced_at = None
    stats_source = "database"

    if user.role == "seller" and user.seller_id:
      seller = Seller.objects.filter(pk=user.seller_id).first()
      if seller and seller.wb_counts_synced_at:
        new_orders = seller.wb_count_new
        in_assembly = seller.wb_count_assembly
        in_delivery = seller.wb_count_delivery
        counts_synced_at = seller.wb_counts_synced_at
        stats_source = "cache"
      else:
        new_orders = orders_qs.filter(wb_supplier_status=WB_SUPPLIER_NEW).count()
        in_assembly = orders_qs.filter(wb_supplier_status="confirm").count()
        in_delivery = orders_qs.filter(wb_in_delivery_q()).count()
    else:
      sellers_qs = Seller.objects.filter(is_active=True)
      sync_meta = sellers_qs.aggregate(
        new_orders=Sum("wb_count_new"),
        in_assembly=Sum("wb_count_assembly"),
        in_delivery=Sum("wb_count_delivery"),
        counts_synced_at=Max("wb_counts_synced_at"),
      )
      if sync_meta["counts_synced_at"]:
        new_orders = sync_meta["new_orders"] or 0
        in_assembly = sync_meta["in_assembly"] or 0
        in_delivery = sync_meta["in_delivery"] or 0
        counts_synced_at = sync_meta["counts_synced_at"]
        stats_source = "cache"
      else:
        new_orders = orders_qs.filter(wb_supplier_status=WB_SUPPLIER_NEW).count()
        in_assembly = orders_qs.filter(wb_supplier_status="confirm").count()
        in_delivery = orders_qs.filter(wb_in_delivery_q()).count()

    data = {
      "orders_today": orders_today,
      "in_picking": in_picking,
      "new_orders": new_orders,
      "in_assembly": in_assembly,
      "in_delivery": in_delivery,
      "stats_source": stats_source,
      "counts_synced_at": (
        counts_synced_at.isoformat() if counts_synced_at else None
      ),
    }

    if user.role in ("admin", "manager"):
      data["sellers_count"] = Seller.objects.filter(is_active=True).count()

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
      dashboard_stats = _dashboard_stats_from_counts(
        result.get("live_counts") or result.get("wb_counts") or {},
      )
      return Response({"success": True, "dashboard_stats": dashboard_stats, **result})

    if user.role not in ("admin", "manager"):
      return Response(status=status.HTTP_403_FORBIDDEN)

    if seller_id:
      seller = Seller.objects.get(pk=seller_id, is_active=True)
      try:
        result = sync_orders_for_seller(seller, user=user)
      except SyncError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
      dashboard_stats = _dashboard_stats_from_counts(
        result.get("live_counts") or result.get("wb_counts") or {},
      )
      return Response({"success": True, "dashboard_stats": dashboard_stats, **result})

    payload = sync_all_active_sellers(user=user)
    results = payload.get("results") or []
    if results:
      payload["dashboard_stats"] = _aggregate_sync_dashboard_stats(results)
      totals = {
        "statuses_updated": sum(r.get("statuses_updated", 0) for r in results),
        "statuses_fetched": sum(r.get("statuses_fetched", 0) for r in results),
        "reconciled": sum(r.get("reconciled", 0) for r in results),
        "raw_total": sum(r.get("raw_total", 0) for r in results),
        "fetched": sum(r.get("fetched", 0) for r in results),
        "created": sum(r.get("created", 0) for r in results),
      }
      payload.update(totals)
      if results[0].get("sync_version"):
        payload["sync_version"] = results[0]["sync_version"]
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
    orders_qs = filter_orders_queryset(
      Order.objects.filter(seller=seller).select_related("product", "product__cell"),
      seller=seller,
    )
    if stage in WB_STAGE_QUERIES:
      orders_qs = orders_qs.filter(WB_STAGE_QUERIES[stage]())
    elif stage:
      orders_qs = orders_qs.filter(status=stage)
    else:
      orders_qs = orders_qs.filter(wb_active_q()).exclude(status=Order.Status.CANCELLED)

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

    warehouses = SellerWarehouse.objects.filter(seller=seller).order_by("name", "wb_warehouse_id")

    return Response({
      "seller": {"id": seller.id, "company_name": seller.company_name},
      "counts": counts,
      "supplies_forming": supplies_forming,
      "warehouses": SellerWarehouseSerializer(warehouses, many=True).data,
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
  """Скан баркода заказа: без ЧЗ — сразу печать; с ЧЗ — ожидание DataMatrix."""
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, seller_id):
    seller = Seller.objects.filter(pk=seller_id, is_active=True).first()
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)

    serializer = ScanPrintSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    try:
      result = scan_order_barcode(
        seller,
        serializer.validated_data["barcode"],
        user=request.user,
      )
    except AssemblyError as exc:
      return Response(
        {"detail": str(exc), "code": exc.code},
        status=status.HTTP_400_BAD_REQUEST,
      )

    order_data = OrderPrintSerializer(result["order"]).data
    payload = {
      "success": True,
      "action": result["action"],
      "requires_marking": result["requires_marking"],
      "order": order_data,
    }
    if result.get("message"):
      payload["message"] = result["message"]
    return Response(payload)


class AssemblyBindMarkingView(APIView):
  """Скан DataMatrix → привязка ЧЗ в WB → печать стикера."""
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, seller_id):
    seller = Seller.objects.filter(pk=seller_id, is_active=True).first()
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)

    serializer = BindMarkingSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    try:
      order = bind_marking_and_print(
        seller,
        serializer.validated_data["order_id"],
        serializer.validated_data["marking_code"],
        user=request.user,
      )
    except AssemblyError as exc:
      return Response(
        {"detail": str(exc), "code": exc.code},
        status=status.HTTP_400_BAD_REQUEST,
      )

    return Response({
      "success": True,
      "action": "print",
      "order": OrderPrintSerializer(order).data,
    })


class AssemblyReplaceOrderView(APIView):
  """Сброс заказа для замены товара."""
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, seller_id):
    seller = Seller.objects.filter(pk=seller_id, is_active=True).first()
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)

    serializer = ReplaceOrderSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    try:
      order = replace_order_item(
        seller,
        serializer.validated_data["order_id"],
        user=request.user,
      )
    except AssemblyError as exc:
      return Response(
        {"detail": str(exc), "code": exc.code},
        status=status.HTTP_400_BAD_REQUEST,
      )

    return Response({
      "success": True,
      "order": OrderAssemblySerializer(order).data,
      "message": f"Заказ WB #{order.wb_order_id} сброшен — возьмите другой экземпляр товара",
    })
