from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsManager
from apps.accounts.tenant import get_seller_for_user, get_supply_for_user, sellers_for_user
from apps.integrations.marketplace import OZON, WB, filter_sellers_qs, parse_marketplace
from apps.sellers.models import Seller, SellerWarehouse
from apps.sellers.serializers import SellerWarehouseSerializer

from apps.orders.services.assembly import AssemblyError
from apps.orders.services.supply_flow import (
  delivery_stage_orders_queryset,
  get_assembly_stage_counts,
  new_stage_orders_queryset,
)
from apps.orders.services.wb_status import WB_STAGE_QUERIES, wb_active_q
from .services.supply_sync import sync_supplies_from_wb
from apps.sellers.services.warehouse_filter import filter_orders_for_assembly, filter_orders_queryset

from .models import Order, PickList, Supply
from .serializers import (
  AssemblyWorkflowModeSerializer,
  BatchBindScanSerializer,
  BindMarkingSerializer,
  OrderActionSerializer,
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
  SupplyBulkDeliverSerializer,
  SupplySerializer,
  VerifyMarkingSerializer,
)
from .services.assembly import (
  AssemblyError,
  bind_marking_and_print,
  fetch_stickers_for_orders,
  get_seller_stage_counts,
  get_seller_wb_tab_counts,
  remove_order_from_assembly,
  replace_order_item,
  scan_order_barcode,
  start_assembly,
)
from .services.marking_queue import get_marking_queue_status
from .services.marking_verification import verify_marking_orders
from .services.supply_flow import (
  SupplyFlowError,
  fetch_supply_barcode,
  refresh_supply_readiness,
  send_order_to_assembly,
  send_order_to_delivery,
  send_orders_to_assembly_bulk,
  send_supplies_to_delivery_bulk,
  send_supply_to_delivery,
)
from .services.pick_list import PickListError, delete_active_pick_list, generate_pick_list, preview_pick_list
from .services.batch_assembly import (
  bind_ozon_batch_scan,
  bind_wb_batch_scan,
  generate_ozon_pick_list,
  get_ozon_batch_ribbon,
  get_wb_batch_ribbon,
)
from .services.ozon_assembly import OzonAssemblyError
from .services.sync_orders import SyncError, sync_all_active_sellers, sync_orders_for_seller


def _assembly_error_response(exc: AssemblyError, *, status_code=status.HTTP_400_BAD_REQUEST):
  payload = {"detail": str(exc), "code": exc.code}
  if exc.order is not None:
    payload["order"] = OrderPrintSerializer(exc.order).data
  return Response(payload, status=status_code)


def _dashboard_stats_from_counts(counts: dict) -> dict:
  return {
    "new_orders": int(counts.get("new", 0) or 0),
    "in_assembly": int(counts.get("in_picking", 0) or 0),
    "in_delivery": int(counts.get("in_delivery", 0) or 0),
  }


def _aggregate_sync_dashboard_stats(results: list[dict]) -> dict:
  totals = {"new": 0, "in_picking": 0, "in_delivery": 0}
  for item in results:
    src = item.get("wb_counts") or item.get("live_counts") or {}
    totals["new"] += int(src.get("new", 0) or 0)
    totals["in_picking"] += int(src.get("in_picking", 0) or 0)
    totals["in_delivery"] += int(src.get("in_delivery", 0) or 0)
  return _dashboard_stats_from_counts(totals)


def _stage_totals_for_sellers(sellers) -> tuple[dict[str, int], object | None]:
  totals = {"new": 0, "in_picking": 0, "in_delivery": 0}
  latest_sync = None
  for seller in sellers:
    counts = get_seller_wb_tab_counts(seller)
    totals["new"] += counts["new"]
    totals["in_picking"] += counts["in_picking"]
    totals["in_delivery"] += counts["in_delivery"]
    if seller.wb_counts_synced_at and (
      latest_sync is None or seller.wb_counts_synced_at > latest_sync
    ):
      latest_sync = seller.wb_counts_synced_at
  return totals, latest_sync


def _orders_queryset_for_user(user):
  qs = Order.objects.select_related("seller", "product", "product__cell")
  if user.role == "seller":
    if not user.seller_id:
      return qs.none()
    qs = qs.filter(seller_id=user.seller_id)
    return filter_orders_queryset(qs, seller=get_seller_for_user(user, user.seller_id))
  fulfillment = sellers_for_user(user)
  return filter_orders_queryset(qs.filter(seller__in=fulfillment))


def _pick_lists_queryset_for_user(user):
  qs = PickList.objects.select_related("seller").prefetch_related("items__cell", "items__product")
  if user.role == "seller":
    if not user.seller_id:
      return qs.none()
    return qs.filter(seller_id=user.seller_id)
  return qs.filter(seller__in=sellers_for_user(user))


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
    from apps.orders.services.ozon_counts import _stage_totals_ozon

    marketplace = parse_marketplace(request)
    counts_synced_at = None
    stats_source = "ozon_api_cache" if marketplace == OZON else "wb_api_cache"

    if user.role == "seller" and user.seller_id:
      seller = get_seller_for_user(user, user.seller_id)
      if seller:
        if marketplace == OZON:
          counts, latest_sync = _stage_totals_ozon([seller] if seller.ozon_enabled else [])
        else:
          counts, latest_sync = _stage_totals_for_sellers([seller] if seller.wb_enabled else [])
        new_orders = counts["new"]
        in_assembly = counts["in_picking"]
        in_delivery = counts["in_delivery"]
        counts_synced_at = latest_sync
      else:
        new_orders = in_assembly = in_delivery = 0
    else:
      sellers_qs = filter_sellers_qs(sellers_for_user(user).filter(is_active=True), marketplace)
      if marketplace == OZON:
        counts, latest_sync = _stage_totals_ozon(sellers_qs)
      else:
        counts, latest_sync = _stage_totals_for_sellers(sellers_qs)
      new_orders = counts["new"]
      in_assembly = counts["in_picking"]
      in_delivery = counts["in_delivery"]
      counts_synced_at = latest_sync

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
      data["sellers_count"] = filter_sellers_qs(
        sellers_for_user(user).filter(is_active=True),
        marketplace,
      ).count()
      if marketplace == WB:
        from apps.orders.services.off_crm_shipments import pending_off_crm_count

        seller_ids = list(sellers_for_user(user).values_list("id", flat=True))
        data["off_crm_pending_count"] = pending_off_crm_count(seller_ids=seller_ids)

    products_qs = Product.objects.filter(
      marketplace=marketplace,
      seller__in=sellers_for_user(user),
    )
    if user.role == "seller" and user.seller_id:
      products_qs = products_qs.filter(seller_id=user.seller_id)
    data["sku_count"] = products_qs.count()

    return Response(data)


class OrderSyncView(APIView):
  permission_classes = [IsAuthenticated]

  def post(self, request):
    user = request.user
    marketplace = parse_marketplace(request)
    serializer = OrderSyncSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    seller_id = serializer.validated_data.get("seller_id")
    sync_mode = serializer.validated_data.get("mode", "full")

    if marketplace == OZON:
      from apps.orders.services.ozon_counts import OzonCountsError, _stage_totals_ozon
      from apps.orders.services.ozon_postings import OzonPostingSyncError, sync_ozon_postings
      from apps.sellers.services.sync_ozon_warehouses import OzonWarehouseSyncError, sync_seller_ozon_warehouses

      if user.role == "seller":
        sellers = sellers_for_user(user).filter(ozon_enabled=True)
      elif seller_id:
        sellers = sellers_for_user(user).filter(pk=seller_id, is_active=True, ozon_enabled=True)
      else:
        sellers = sellers_for_user(user).filter(is_active=True, ozon_enabled=True)

      errors = []
      refreshed = 0
      fetched = 0
      for seller in sellers:
        if not seller.ozon_client_id or not seller.ozon_api_key_encrypted:
          continue
        try:
          try:
            sync_seller_ozon_warehouses(seller, user=user)
          except OzonWarehouseSyncError:
            pass
          stats = sync_ozon_postings(seller, user=user)
          fetched += int(stats.get("created", 0)) + int(stats.get("updated", 0))
          refreshed += 1
        except (OzonPostingSyncError, OzonCountsError) as exc:
          errors.append({"seller_id": seller.id, "error": str(exc)})

      counts, _latest = _stage_totals_ozon(sellers)
      return Response({
        "success": True,
        "marketplace": OZON,
        "refreshed": refreshed,
        "fetched": fetched,
        "statuses_updated": fetched,
        "errors": errors,
        "dashboard_stats": {
          "new_orders": counts["new"],
          "in_assembly": counts["in_picking"],
          "in_delivery": counts["in_delivery"],
        },
        "message": (
          "Склады и отправления Ozon обновлены."
          if refreshed
          else "Нет селлеров с ключами Ozon. Добавьте Client-Id и Api-Key в «Селлеры»."
        ),
      })

    if user.role == "seller":
      if not user.seller_id:
        return Response(
          {"detail": "У пользователя не привязан селлер"},
          status=status.HTTP_400_BAD_REQUEST,
        )
      try:
        result = sync_orders_for_seller(user.seller, user=user, mode=sync_mode)
      except SyncError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
      dashboard_stats = _dashboard_stats_from_counts(
        result.get("wb_counts") or result.get("live_counts") or {},
      )
      return Response({"success": True, "dashboard_stats": dashboard_stats, **result})

    if user.role not in ("admin", "manager"):
      return Response(status=status.HTTP_403_FORBIDDEN)

    if seller_id:
      seller = get_seller_for_user(user, seller_id, active_only=True)
      if not seller:
        return Response(status=status.HTTP_404_NOT_FOUND)
      try:
        result = sync_orders_for_seller(seller, user=user, mode=sync_mode)
      except SyncError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
      dashboard_stats = _dashboard_stats_from_counts(
        result.get("wb_counts") or result.get("live_counts") or {},
      )
      return Response({"success": True, "dashboard_stats": dashboard_stats, **result})

    from apps.accounts.tenant import get_user_fulfillment

    payload = sync_all_active_sellers(
      user=user,
      mode=sync_mode,
      fulfillment=get_user_fulfillment(user),
    )
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
    seller = get_seller_for_user(request.user, serializer.validated_data["seller_id"], active_only=True)
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)

    try:
      pick_list = generate_pick_list(
        seller,
        user=request.user,
        force=bool(serializer.validated_data.get("force")),
        stage=serializer.validated_data.get("stage") or "new",
      )
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
    marketplace = parse_marketplace(request)
    sellers = filter_sellers_qs(
      sellers_for_user(request.user).filter(is_active=True),
      marketplace,
    ).order_by("company_name")
    payload = []
    for seller in sellers:
      if marketplace == OZON:
        from apps.orders.services.ozon_counts import get_seller_ozon_tab_counts

        tab_counts = get_seller_ozon_tab_counts(seller, assembly_only=True)
        stage_counts = {
          "assembled": 0,
          "label_printed": 0,
          "marked": 0,
          "in_supply": 0,
          "shipped": 0,
          "cancelled": 0,
        }
      else:
        tab_counts = get_seller_wb_tab_counts(seller, assembly_only=True)
        stage_counts = get_seller_stage_counts(seller, assembly_only=True)
      total_active = tab_counts["new"] + tab_counts["in_picking"] + tab_counts["in_delivery"]
      payload.append({
        "id": seller.id,
        "company_name": seller.company_name,
        **stage_counts,
        "new": tab_counts["new"],
        "in_picking": tab_counts["in_picking"],
        "in_delivery": tab_counts["in_delivery"],
        "total_active": total_active,
        "marketplace": marketplace,
        "has_ozon_api": bool(seller.ozon_client_id and seller.ozon_api_key_encrypted),
      })
    return Response(SellerAssemblyCountersSerializer(payload, many=True).data)


class AssemblySellerDetailView(APIView):
  """Кабинет сборки конкретного селлера."""
  permission_classes = [IsAuthenticated, IsManager]

  def get(self, request, seller_id):
    seller = get_seller_for_user(request.user, seller_id, active_only=True)
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)

    marketplace = parse_marketplace(request)
    if marketplace == OZON:
      from apps.orders.views_ozon import OzonAssemblySellerDetailView

      stage = request.query_params.get("stage", "new")
      return Response(OzonAssemblySellerDetailView.payload(seller, stage))

    stage_counts = get_seller_stage_counts(seller, assembly_only=True)
    tab_counts = get_seller_wb_tab_counts(seller, assembly_only=True)
    assembly_counts = get_assembly_stage_counts(seller)
    counts = {
      **stage_counts,
      **tab_counts,
      "new": assembly_counts["new"],
      "in_picking": assembly_counts["in_picking"],
      "in_delivery": assembly_counts["in_delivery"],
    }
    stage = request.query_params.get("stage", "")
    visible_orders = Order.objects.filter(seller=seller, assembly_hidden=False)
    if stage == "new":
      orders_qs = new_stage_orders_queryset(seller).select_related(
        "product", "product__cell",
      )
    elif stage == "complete":
      orders_qs = delivery_stage_orders_queryset(seller).select_related(
        "product", "product__cell",
      )
    else:
      orders_qs = filter_orders_for_assembly(
        visible_orders.select_related("product", "product__cell"),
        seller,
      )
      if stage in WB_STAGE_QUERIES:
        orders_qs = orders_qs.filter(WB_STAGE_QUERIES[stage]())
      elif stage:
        orders_qs = orders_qs.filter(status=stage)
      else:
        orders_qs = orders_qs.filter(wb_active_q()).exclude(status=Order.Status.CANCELLED)

    orders = orders_qs.order_by("-created_at")[:300]

    active_pick_list = (
      PickList.objects.filter(seller=seller, is_completed=False, marketplace=WB)
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
      "assembly_workflow_mode": seller.assembly_workflow_mode,
      "counts": counts,
      "assembly_eligible": assembly_counts["new"],
      "supplies_forming": supplies_forming,
      "warehouses": SellerWarehouseSerializer(warehouses, many=True).data,
      "orders": OrderAssemblySerializer(orders, many=True).data,
      "active_pick_list": (
        PickListSerializer(active_pick_list).data if active_pick_list else None
      ),
    })


class AssemblyStartView(APIView):
  """Передать заказы на сборку в WB + стикеры."""
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, seller_id):
    seller = get_seller_for_user(request.user, seller_id, active_only=True)
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)

    try:
      result = start_assembly(seller, user=request.user)
    except AssemblyError as exc:
      return _assembly_error_response(exc)

    return Response({
      "success": True,
      **result,
      "pick_list": None,
    }, status=status.HTTP_201_CREATED)


class AssemblyPickListPreviewView(APIView):
  """Сформировать лист подбора PDF по включённым складам (без отправки в WB)."""
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, seller_id):
    seller = get_seller_for_user(request.user, seller_id, active_only=True)
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)

    stage = "new"
    if isinstance(request.data, dict):
      stage = (request.data.get("stage") or "new").strip() or "new"
    if stage not in ("new", "confirm"):
      return Response({"detail": "stage должен быть new или confirm"}, status=400)

    try:
      pick_list = preview_pick_list(seller, stage=stage, user=request.user)
    except PickListError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    return Response({"success": True, "pick_list": pick_list})


class AssemblyDeletePickListView(APIView):
  """Удалить активный лист подбора и вернуть заказы в «Новые»."""
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, seller_id):
    seller = get_seller_for_user(request.user, seller_id, active_only=True)
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)

    pick_list_id = request.data.get("pick_list_id") if isinstance(request.data, dict) else None
    try:
      result = delete_active_pick_list(
        seller,
        pick_list_id=int(pick_list_id) if pick_list_id else None,
        user=request.user,
      )
    except PickListError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    return Response({"success": True, **result})


class AssemblyDeleteOrderView(APIView):
  """Удалить заказ из сборки FBS (скрыть с вкладок, с подтверждением на фронте)."""
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, seller_id):
    seller = get_seller_for_user(request.user, seller_id, active_only=True)
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)

    serializer = OrderActionSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    try:
      result = remove_order_from_assembly(
        seller,
        serializer.validated_data["order_id"],
        user=request.user,
      )
    except AssemblyError as exc:
      return _assembly_error_response(exc)

    order = result["order"]
    return Response({
      "success": True,
      "order": OrderAssemblySerializer(order).data,
      "counts": result["counts"],
      "assembly_eligible": result["assembly_eligible"],
    })


class AssemblyScanPrintView(APIView):
  """Скан баркода заказа: без ЧЗ — сразу печать; с ЧЗ — ожидание DataMatrix."""
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, seller_id):
    seller = get_seller_for_user(request.user, seller_id, active_only=True)
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
      return _assembly_error_response(exc)

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
  """Скан DataMatrix → привязка ЧЗ в WB → ожидание проверки."""
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, seller_id):
    seller = get_seller_for_user(request.user, seller_id, active_only=True)
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)

    serializer = BindMarkingSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    try:
      result = bind_marking_and_print(
        seller,
        serializer.validated_data["order_id"],
        serializer.validated_data["marking_code"],
        user=request.user,
      )
    except AssemblyError as exc:
      return _assembly_error_response(exc)

    order_data = OrderPrintSerializer(result["order"]).data
    payload = {
      "success": True,
      "action": result["action"],
      "order": order_data,
    }
    if result.get("message"):
      payload["message"] = result["message"]
    return Response(payload)


class AssemblyMarkingStatusView(APIView):
  """Счётчики и списки очереди ЧЗ (ошибки / без привязки)."""
  permission_classes = [IsAuthenticated, IsManager]

  def get(self, request, seller_id):
    seller = get_seller_for_user(request.user, seller_id, active_only=True)
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)

    status_data = get_marking_queue_status(seller)
    return Response({
      "success": True,
      "errors_count": status_data["errors_count"],
      "unbound_count": status_data["unbound_count"],
      "errors": OrderAssemblySerializer(status_data["errors"], many=True).data,
      "unbound": OrderAssemblySerializer(status_data["unbound"], many=True).data,
    })


class AssemblyVerifyMarkingView(APIView):
  """Опрос статуса проверки ЧЗ в WB."""
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, seller_id):
    seller = get_seller_for_user(request.user, seller_id, active_only=True)
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)

    serializer = VerifyMarkingSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    order_ids = serializer.validated_data.get("order_ids") or []

    try:
      results = verify_marking_orders(seller, order_ids or None, user=request.user)
    except AssemblyError as exc:
      return _assembly_error_response(exc)

    orders_by_id = {
      order.id: OrderPrintSerializer(order).data
      for order in Order.objects.filter(seller=seller, pk__in=[r["order_id"] for r in results])
    }
    for item in results:
      item["order"] = orders_by_id.get(item["order_id"])

    return Response({
      "success": True,
      "results": results,
    })


class AssemblyWorkflowModeView(APIView):
  """Режим сборки FBS: scan (пошагово) или batch (лента стикеров)."""
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, seller_id):
    seller = get_seller_for_user(request.user, seller_id, active_only=True)
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)

    serializer = AssemblyWorkflowModeSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    seller.assembly_workflow_mode = serializer.validated_data["mode"]
    seller.save(update_fields=["assembly_workflow_mode", "updated_at"])
    return Response({
      "success": True,
      "assembly_workflow_mode": seller.assembly_workflow_mode,
    })


class AssemblyBatchRibbonView(APIView):
  """Данные для печати ленты: инфо-стикер 58×40 + стикеры заказов по группам баркода."""
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, seller_id):
    seller = get_seller_for_user(request.user, seller_id, active_only=True)
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)

    marketplace = parse_marketplace(request)
    try:
      if marketplace == OZON:
        ribbon = get_ozon_batch_ribbon(seller)
      else:
        ribbon = get_wb_batch_ribbon(seller)
    except AssemblyError as exc:
      return _assembly_error_response(exc)

    return Response({"success": True, **ribbon})


class AssemblyBatchBindView(APIView):
  """Связка баркод + стикер (+ ЧЗ) в режиме ленты; автоопределение типа скана."""
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, seller_id):
    seller = get_seller_for_user(request.user, seller_id, active_only=True)
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)

    serializer = BatchBindScanSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    marketplace = parse_marketplace(request)

    try:
      if marketplace == OZON:
        result = bind_ozon_batch_scan(
          seller,
          scan=data.get("scan") or "",
          barcode=data.get("barcode") or "",
          sticker_scan=data.get("sticker_scan") or "",
          marking_code=data.get("marking_code") or "",
          user=request.user,
        )
      else:
        result = bind_wb_batch_scan(
          seller,
          scan=data.get("scan") or "",
          barcode=data.get("barcode") or "",
          sticker_scan=data.get("sticker_scan") or "",
          marking_code=data.get("marking_code") or "",
          user=request.user,
        )
    except AssemblyError as exc:
      return _assembly_error_response(exc)
    except OzonAssemblyError as exc:
      return _error_response_ozon(exc)

    payload = {"success": True, **result}
    if result.get("complete") and result.get("order_id"):
      order = Order.objects.filter(pk=result["order_id"], seller=seller).first()
      if order:
        payload["order"] = OrderPrintSerializer(order).data
    return Response(payload)


def _error_response_ozon(exc):
  payload = {"detail": str(exc)}
  code = getattr(exc, "code", "") or ""
  if code:
    payload["code"] = code
  return Response(payload, status=status.HTTP_400_BAD_REQUEST)


class AssemblyOzonPickListView(APIView):
  """Сформировать лист подбора Ozon из отправлений на сборке."""
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, seller_id):
    seller = get_seller_for_user(request.user, seller_id, active_only=True)
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)

    try:
      pick_list = generate_ozon_pick_list(seller, user=request.user)
    except PickListError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    pick_list = (
      PickList.objects.filter(pk=pick_list.pk)
      .prefetch_related("items__cell", "items__product")
      .first()
    )
    return Response({
      "success": True,
      "pick_list": PickListSerializer(pick_list).data,
    }, status=status.HTTP_201_CREATED)


class AssemblyReplaceOrderView(APIView):
  """Сброс заказа для замены товара."""
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, seller_id):
    seller = get_seller_for_user(request.user, seller_id, active_only=True)
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
      return _assembly_error_response(exc)

    return Response({
      "success": True,
      "order": OrderAssemblySerializer(order).data,
      "message": f"Заказ WB #{order.wb_order_id} сброшен — возьмите другой экземпляр товара",
    })


class AssemblyReprintStickerView(APIView):
  """Повторная печать стикера FBS (если повреждён)."""
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, seller_id):
    seller = get_seller_for_user(request.user, seller_id, active_only=True)
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)

    serializer = OrderActionSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    order = Order.objects.filter(
      pk=serializer.validated_data["order_id"],
      seller=seller,
    ).first()
    if not order:
      return Response({"detail": "Заказ не найден"}, status=status.HTTP_404_NOT_FOUND)

    if not order.sticker_file:
      try:
        fetch_stickers_for_orders(seller, [order], user=request.user)
      except AssemblyError as exc:
        return _assembly_error_response(exc)
      order.refresh_from_db()

    if not order.sticker_file:
      return Response(
        {
          "detail": "Стикер не загружен. Нажмите «Лист подбора» или обновите заказы из WB.",
          "code": "no_sticker",
        },
        status=status.HTTP_400_BAD_REQUEST,
      )

    return Response({
      "success": True,
      "action": "print",
      "order": OrderPrintSerializer(order).data,
    })


class AssemblySendToAssemblyView(APIView):
  """Отправить один заказ на сборку в WB (new → confirm)."""
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, seller_id):
    seller = get_seller_for_user(request.user, seller_id, active_only=True)
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)

    serializer = OrderActionSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    try:
      result = send_order_to_assembly(
        seller,
        serializer.validated_data["order_id"],
        user=request.user,
      )
    except SupplyFlowError as exc:
      return _assembly_error_response(exc)

    payload = {
      "success": True,
      "order": OrderAssemblySerializer(result["order"]).data,
      "wb_supply_id": result["wb_supply_id"],
      "stickers_fetched": result["stickers_fetched"],
    }
    if result.get("sticker_error"):
      payload["sticker_error"] = result["sticker_error"]
    return Response(payload)


class AssemblySendToDeliveryView(APIView):
  """Отправить один заказ в доставку в WB (confirm → complete+waiting)."""
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, seller_id):
    seller = get_seller_for_user(request.user, seller_id, active_only=True)
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)

    serializer = OrderActionSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    try:
      result = send_order_to_delivery(
        seller,
        serializer.validated_data["order_id"],
        user=request.user,
      )
    except SupplyFlowError as exc:
      return _assembly_error_response(exc)

    payload = {
      "success": True,
      "order": OrderAssemblySerializer(result["order"]).data,
      "wb_supply_id": result["wb_supply_id"],
    }
    if result.get("supply_barcode_file"):
      payload["supply_barcode_file"] = result["supply_barcode_file"]
    if result.get("supply_barcode"):
      payload["supply_barcode"] = result["supply_barcode"]
    if result.get("stock"):
      payload["stock"] = result["stock"]
    return Response(payload)


class AssemblySendAllToAssemblyView(APIView):
  """Отправить на сборку все новые заказы селлера (по одному supply на заказ)."""
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, seller_id):
    seller = get_seller_for_user(request.user, seller_id, active_only=True)
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)

    order_ids = request.data.get("order_ids") if isinstance(request.data, dict) else None
    if order_ids is not None and not isinstance(order_ids, list):
      return Response(
        {"detail": "order_ids должен быть списком"},
        status=status.HTTP_400_BAD_REQUEST,
      )

    try:
      result = send_orders_to_assembly_bulk(
        seller,
        order_ids=order_ids,
        user=request.user,
      )
    except SupplyFlowError as exc:
      return _assembly_error_response(exc)

    return Response({"success": True, **result})


class SupplyListView(APIView):
  """Список поставок селлера."""
  permission_classes = [IsAuthenticated, IsManager]

  def get(self, request):
    seller_id = request.query_params.get("seller_id")
    if not seller_id:
      return Response(
        {"detail": "Укажите seller_id"},
        status=status.HTTP_400_BAD_REQUEST,
      )

    seller = get_seller_for_user(request.user, seller_id, active_only=True)
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)

    status_filter = request.query_params.get("status", "").strip()
    sync_wb = request.query_params.get("sync", "1") != "0"
    include_closed = (
      status_filter == Supply.Status.CONFIRMED
      or not status_filter
    )

    sync_stats = None
    if sync_wb:
      try:
        sync_stats = sync_supplies_from_wb(
          seller,
          include_closed=include_closed,
        )
      except AssemblyError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    qs = (
      Supply.objects.filter(seller=seller)
      .select_related("seller")
      .prefetch_related("orders__product", "orders__seller")
      .order_by("-created_at")
    )
    if status_filter:
      qs = qs.filter(status=status_filter)
    else:
      qs = qs.filter(
        status__in=(
          Supply.Status.FORMING,
          Supply.Status.READY,
          Supply.Status.CONFIRMED,
        ),
      )

    supplies = list(qs[:500])
    for supply in supplies:
      refresh_supply_readiness(supply)

    payload = SupplySerializer(supplies, many=True).data
    if sync_stats is not None:
      return Response({
        "supplies": payload,
        "sync": sync_stats,
      })
    return Response(payload)


class SupplyDetailView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def get(self, request, supply_id):
    supply = get_supply_for_user(request.user, supply_id)
    refresh_supply_readiness(supply)
    return Response(SupplySerializer(supply).data)


class SupplyDeliverView(APIView):
  """Передать поставку в доставку WB (все заказы должны быть готовы, включая ЧЗ)."""
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, supply_id):
    supply = get_supply_for_user(request.user, supply_id)

    try:
      result = send_supply_to_delivery(supply.seller, supply.id, user=request.user)
    except SupplyFlowError as exc:
      return _assembly_error_response(exc)

    payload = {
      "success": True,
      "message": "Поставка передана в доставку",
      "wb_supply_id": result.get("wb_supply_id", ""),
    }
    if result.get("supply_barcode_file"):
      payload["supply_barcode_file"] = result["supply_barcode_file"]
    if result.get("supply_barcode"):
      payload["supply_barcode"] = result["supply_barcode"]
    return Response(payload)


class SupplyBulkDeliverView(APIView):
  """Массовая передача готовых поставок в доставку."""
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request):
    serializer = SupplyBulkDeliverSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    seller = get_seller_for_user(request.user, data["seller_id"])
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)

    supply_ids = data.get("supply_ids") or None
    try:
      result = send_supplies_to_delivery_bulk(
        seller,
        supply_ids=supply_ids,
        user=request.user,
      )
    except SupplyFlowError as exc:
      return _assembly_error_response(exc)

    return Response({
      "success": True,
      "message": f"Передано в доставку: {result['delivered']} поставок",
      **result,
    })


class SupplyBarcodeView(APIView):
  """Повторная печать QR/ШК поставки."""
  permission_classes = [IsAuthenticated, IsManager]

  def get(self, request, supply_id):
    supply = get_supply_for_user(request.user, supply_id)

    try:
      result = fetch_supply_barcode(supply.seller, supply.id)
    except SupplyFlowError as exc:
      return _assembly_error_response(exc)

    return Response({"success": True, **result})
