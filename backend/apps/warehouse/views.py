from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsManager
from apps.accounts.tenant import get_product_for_user, get_seller_for_user, sellers_for_user, stock_operations_for_user
from apps.integrations.marketplace import OZON, filter_sellers_qs, parse_marketplace
from apps.sellers.models import Seller

from .models import Cell, Product, StockOperation
from .serializers import (
  CellSerializer,
  IntakeSerializer,
  InventorySerializer,
  MoveCellSerializer,
  OnboardingConfirmSerializer,
  OnboardingExcludeSerializer,
  OnboardingPreviewSerializer,
  ProductSerializer,
  CellDetailSerializer,
  SellerBriefSerializer,
  StockFileApplySerializer,
  StockOperationSerializer,
  StockTransferSerializer,
  StockTransferBulkSerializer,
  StockDistributeSerializer,
  WbSyncAutoSerializer,
  WbSyncPreviewSerializer,
)
from .services.cell_label import build_cell_label_data
from .services.cell_move import CellMoveError, move_product_to_cell
from .services.cells import cells_queryset_ordered
from .services.catalog_fetch import CatalogError, apply_exclusions_and_renumber, build_onboarding_preview
from .services.catalog_fetch_ozon import build_ozon_onboarding_preview
from .services.intake import IntakeError, perform_intake
from .services.inventory import perform_inventory
from .services.onboarding import OnboardingError, confirm_onboarding
from .services.stock_file_import import (
  StockFileImportError,
  apply_stock_import,
  build_stock_import_preview,
)
from .services.stock_transfer import (
  StockTransferError,
  build_stock_overview,
  distribute_stocks_evenly_bulk,
  perform_stock_transfer,
  transfer_stocks_bulk,
)
from .services.wb_stocks import WBStockError, fetch_wb_stock_for_barcode, get_seller_warehouse
from .services.wb_sync_intake import (
  WbSyncIntakeError,
  apply_wb_sync_auto,
  preview_wb_sync_intake,
  serialize_preview,
)
from .services.marking_lookup import lookup_marking_for_barcode, refresh_product_marking
from .services.wb_product_sync import refresh_seller_products_from_wb


def _require_seller(request, seller_id):
  seller = get_seller_for_user(request.user, seller_id, active_only=True)
  if not seller:
    from django.http import Http404
    raise Http404
  return seller


class SellerListView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def get(self, request):
    marketplace = parse_marketplace(request)
    sellers = filter_sellers_qs(
      sellers_for_user(request.user).filter(is_active=True),
      marketplace,
    ).order_by("company_name")
    return Response(SellerBriefSerializer(sellers, many=True).data)


class CellListView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def get(self, request):
    seller_id = request.query_params.get("seller_id")
    if not seller_id:
      return Response(
        {"detail": "Укажите seller_id"},
        status=status.HTTP_400_BAD_REQUEST,
      )

    free_only = request.query_params.get("free") == "1"
    marketplace = parse_marketplace(request)
    if not get_seller_for_user(request.user, seller_id, active_only=True):
      return Response(status=status.HTTP_404_NOT_FOUND)
    cells = cells_queryset_ordered(
      Cell.objects.filter(seller_id=seller_id, marketplace=marketplace)
    )
    if free_only:
      cells = cells.filter(is_occupied=False)
    return Response(CellSerializer(cells, many=True).data)


class CellDetailView(APIView):
  """Поиск ячейки по номеру — товар, баркод, артикул, размер, фото."""
  permission_classes = [IsAuthenticated, IsManager]

  def get(self, request, seller_id, cell_number):
    seller = _require_seller(request, seller_id)
    marketplace = parse_marketplace(request)
    number = str(cell_number).strip()
    if not number:
      return Response({"detail": "Укажите номер ячейки"}, status=status.HTTP_400_BAD_REQUEST)

    cell = Cell.objects.filter(seller=seller, marketplace=marketplace, number=number).first()
    if not cell:
      return Response({"detail": f"Ячейка №{number} не найдена"}, status=status.HTTP_404_NOT_FOUND)

    product = (
      Product.objects.filter(cell=cell, seller=seller, marketplace=marketplace)
      .select_related("cell", "seller")
      .first()
    )
    return Response(CellDetailSerializer({"cell": cell, "product": product}).data)


class SellerProductsView(APIView):
  """Товары селлера по ячейкам — для печати этикеток и переноса."""
  permission_classes = [IsAuthenticated, IsManager]

  def get(self, request, seller_id):
    seller = _require_seller(request, seller_id)
    marketplace = parse_marketplace(request)
    products = (
      Product.objects.filter(seller=seller, marketplace=marketplace)
      .select_related("cell", "seller")
      .order_by("cell__number")
    )
    products = sorted(products, key=lambda p: int(p.cell.number) if p.cell.number.isdigit() else p.cell.number)
    return Response(ProductSerializer(products, many=True).data)


class SellerProductsRefreshView(APIView):
  """Подтянуть названия и маркировку всех товаров селлера из WB."""
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, seller_id):
    seller = _require_seller(request, seller_id)
    result = refresh_seller_products_from_wb(seller)

    if result.error:
      return Response(
        {
          "success": False,
          "detail": result.error,
          "total": result.total,
          "updated": result.updated,
          "not_found": result.not_found,
        },
        status=status.HTTP_400_BAD_REQUEST,
      )

    message = f"Обновлено {result.updated} из {result.total} товаров"
    if result.not_found:
      message += f", не найдено на WB: {result.not_found}"

    products = (
      Product.objects.filter(seller=seller)
      .select_related("cell", "seller")
      .order_by("cell__number")
    )
    products = sorted(
      products,
      key=lambda p: int(p.cell.number) if p.cell.number.isdigit() else p.cell.number,
    )

    return Response({
      "success": True,
      "message": message,
      "total": result.total,
      "updated": result.updated,
      "not_found": result.not_found,
      "products": ProductSerializer(products, many=True).data,
    })


class ProductCellLabelView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def get(self, request, product_id):
    product = get_product_for_user(request.user, product_id)
    return Response(build_cell_label_data(product))


class ProductMoveCellView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, product_id):
    serializer = MoveCellSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    product = get_product_for_user(request.user, product_id)
    cell_id = serializer.validated_data["cell_id"]
    if not Cell.objects.filter(pk=cell_id, seller_id=product.seller_id).exists():
      return Response({"detail": "Ячейка не найдена у этого селлера"}, status=status.HTTP_400_BAD_REQUEST)
    try:
      product = move_product_to_cell(
        product=product,
        new_cell_id=serializer.validated_data["cell_id"],
        user=request.user,
      )
    except CellMoveError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    return Response({
      "success": True,
      "message": f"Товар перенесён в ячейку №{product.cell.number}",
      "product": ProductSerializer(product).data,
      "print_cell_label": True,
      "cell_label": build_cell_label_data(product),
    })


class IntakeLookupView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def get(self, request):
    barcode = request.query_params.get("barcode", "").strip()
    seller_id = request.query_params.get("seller_id")
    warehouse_id = request.query_params.get("wb_warehouse_id")

    if not barcode or not seller_id:
      return Response(
        {"detail": "Укажите barcode и seller_id"},
        status=status.HTTP_400_BAD_REQUEST,
      )

    seller = _require_seller(request, seller_id)

    wb_stock = None
    warehouse_name = ""
    if warehouse_id:
      try:
        warehouse = get_seller_warehouse(seller, int(warehouse_id))
        warehouse_name = warehouse.name or f"Склад #{warehouse.wb_warehouse_id}"
        wb_stock = fetch_wb_stock_for_barcode(seller, warehouse, barcode)
      except (WBStockError, ValueError) as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    product = (
      Product.objects.filter(
        seller_id=seller_id,
        barcode=barcode,
        marketplace=parse_marketplace(request),
      )
      .select_related("cell", "seller")
      .first()
    )

    if product:
      marking = refresh_product_marking(product, product.seller)
      return Response({
        "exists": True,
        "product": ProductSerializer(product).data,
        "wb_stock": wb_stock,
        "warehouse_name": warehouse_name,
        "marking": {
          "requires_marking": product.requires_marking,
          "wb_found": marking.wb_found,
          "title": marking.title,
          "warning": marking.warning,
        },
      })

    seller = get_seller_for_user(request.user, seller_id, active_only=True)
    if not seller:
      from django.http import Http404
      raise Http404
    marking = lookup_marking_for_barcode(
      seller,
      barcode,
    )
    return Response({
      "exists": False,
      "barcode": barcode,
      "wb_stock": wb_stock,
      "warehouse_name": warehouse_name,
      "marking": {
        "requires_marking": marking.requires_marking,
        "wb_found": marking.wb_found,
        "title": marking.title,
        "warning": marking.warning,
      },
    })


class IntakeView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request):
    marketplace = parse_marketplace(request)
    serializer = IntakeSerializer(data=request.data, context={"marketplace": marketplace})
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    seller = _require_seller(request, data["seller_id"])

    try:
      result = perform_intake(
        seller=seller,
        barcode=data["barcode"],
        quantity=data.get("quantity", 0),
        user=request.user,
        wb_warehouse_id=data.get("wb_warehouse_id"),
        stock_mode=data.get("stock_mode", "intake"),
        verified_stock_match=data.get("verified_stock_match", False),
        cell_mode=data.get("cell_mode", "auto"),
        cell_id=data.get("cell_id"),
        name=data.get("name", ""),
        marketplace=marketplace,
        sync_variant=data.get("sync_variant"),
      )
    except IntakeError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    qty = result.product.quantity
    if marketplace == OZON:
      message = f"Принято {data.get('quantity', 0)} шт. на склад Ozon (CRM)"
    elif result.stock_mode == "sync_from_wb":
      message = (
        f"Остаток CRM установлен по ЛК WB: {qty} шт. "
        f"(склад {result.wb_sync.get('warehouse_name') if result.wb_sync else ''})"
      )
    else:
      added = result.wb_sync.get("added") if result.wb_sync else data.get("quantity", 0)
      message = f"Принято {added} шт. на склад CRM и передано в ЛК WB"

    return Response(
      {
        "success": True,
        "message": message,
        "product": ProductSerializer(result.product).data,
        "print_cell_label": result.print_cell_label,
        "cell_label": result.cell_label,
        "stock_mode": result.stock_mode,
        "wb_sync": result.wb_sync,
      },
      status=status.HTTP_201_CREATED,
    )


class WbSyncIntakePreviewView(APIView):
  """Остатки ЛК WB для сверки: список баркодов с планом ячеек."""
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request):
    serializer = WbSyncPreviewSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    seller = _require_seller(request, data["seller_id"])
    try:
      preview = preview_wb_sync_intake(seller, data["wb_warehouse_id"])
    except WbSyncIntakeError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response({"success": True, **serialize_preview(preview)})


class WbSyncIntakeAutoView(APIView):
  """Автоматическая сверка: CRM = остатки WB, ячейки по плану."""
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request):
    serializer = WbSyncAutoSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    seller = _require_seller(request, data["seller_id"])
    try:
      result = apply_wb_sync_auto(
        seller,
        data["wb_warehouse_id"],
        barcodes=data.get("barcodes"),
        user=request.user,
      )
    except WbSyncIntakeError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    return Response(
      {
        "success": True,
        "message": (
          f"Сверка с WB: создано {result.created}, обновлено {result.updated}, "
          f"пропущено {result.skipped}"
        ),
        "created": result.created,
        "updated": result.updated,
        "skipped": result.skipped,
        "products": ProductSerializer(result.products, many=True).data,
        "cell_labels": result.cell_labels,
      },
      status=status.HTTP_201_CREATED,
    )


class IntakeHistoryView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def get(self, request):
    ops = (
      stock_operations_for_user(request.user)
      .filter(
        operation_type__in=[
          StockOperation.OperationType.INTAKE,
          StockOperation.OperationType.ADJUSTMENT,
        ],
      )
      .select_related("product", "product__cell", "product__seller")
      .order_by("-created_at")[:30]
    )
    return Response(StockOperationSerializer(ops, many=True).data)


class InventoryLookupView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def get(self, request):
    barcode = request.query_params.get("barcode", "").strip()
    seller_id = request.query_params.get("seller_id")

    if not barcode or not seller_id:
      return Response(
        {"detail": "Укажите barcode и seller_id"},
        status=status.HTTP_400_BAD_REQUEST,
      )

    seller = _require_seller(request, seller_id)
    marketplace = parse_marketplace(request)
    product = (
      Product.objects.filter(seller_id=seller_id, barcode=barcode, marketplace=marketplace)
      .select_related("cell", "seller")
      .first()
    )

    if product:
      marking = refresh_product_marking(product, product.seller)
      return Response({
        "exists": True,
        "product": ProductSerializer(product).data,
        "marking": {
          "requires_marking": product.requires_marking,
          "wb_found": marking.wb_found,
          "title": marking.title,
          "warning": marking.warning,
        },
      })

    marking = lookup_marking_for_barcode(seller, barcode)
    return Response({
      "exists": False,
      "barcode": barcode,
      "marking": {
        "requires_marking": marking.requires_marking,
        "wb_found": marking.wb_found,
        "title": marking.title,
        "warning": marking.warning,
      },
    })


class InventoryView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request):
    marketplace = parse_marketplace(request)
    serializer = InventorySerializer(data=request.data, context={"marketplace": marketplace})
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    seller = _require_seller(request, data["seller_id"])

    try:
      result = perform_inventory(
        seller=seller,
        barcode=data["barcode"],
        quantity=data["quantity"],
        warehouse_ids=data.get("warehouse_ids") or [],
        user=request.user,
        cell_mode=data.get("cell_mode", "auto"),
        cell_id=data.get("cell_id"),
        name=data.get("name", ""),
        marketplace=marketplace,
      )
    except IntakeError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    return Response(
      {
        "success": True,
        "verified": result.verified,
        "fulfillment_quantity": result.fulfillment_quantity,
        "wb_total_sent": result.wb_total_sent,
        "wb_total_actual": result.wb_total_actual,
        "wb_total_difference": result.wb_total_difference,
        "warehouses": [
          {
            "warehouse_id": line.warehouse_id,
            "warehouse_name": line.warehouse_name,
            "wb_warehouse_id": line.wb_warehouse_id,
            "sent_amount": line.sent_amount,
            "wb_actual": line.wb_actual,
            "difference": line.difference,
          }
          for line in result.warehouses
        ],
        "product": ProductSerializer(result.product).data,
        "print_cell_label": result.print_cell_label,
        "cell_label": result.cell_label,
      },
      status=status.HTTP_201_CREATED,
    )


class OnboardingPreviewView(APIView):
  """Сценарий 1: каталог WB/Ozon + остатки + план ячеек."""
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, seller_id):
    seller = _require_seller(request, seller_id)
    marketplace = parse_marketplace(request)
    serializer = OnboardingPreviewSerializer(
      data=request.data or {},
      context={"seller_id": seller_id, "marketplace": marketplace},
    )
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    try:
      if marketplace == OZON:
        payload = build_ozon_onboarding_preview(
          seller,
          catalog_mode=data.get("catalog_mode", "all"),
          warehouse_ids=data.get("warehouse_ids"),
        )
      else:
        payload = build_onboarding_preview(
          seller,
          catalog_mode=data.get("catalog_mode", "all"),
          warehouse_ids=data.get("warehouse_ids"),
        )
    except CatalogError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response({"success": True, **payload})


class OnboardingExcludeView(APIView):
  """Пересчитать план после исключения баркодов/артикулов."""
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, seller_id):
    _require_seller(request, seller_id)
    serializer = OnboardingExcludeSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    items = apply_exclusions_and_renumber(
      serializer.validated_data["items"],
      exclude_barcodes=set(serializer.validated_data.get("exclude_barcodes") or []),
      exclude_nm_ids=set(serializer.validated_data.get("exclude_nm_ids") or []),
    )
    return Response({"success": True, "items": items})


class OnboardingConfirmView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, seller_id):
    seller = _require_seller(request, seller_id)
    serializer = OnboardingConfirmSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    try:
      result = confirm_onboarding(
        seller,
        serializer.validated_data["items"],
        user=request.user,
        marketplace=parse_marketplace(request),
      )
    except OnboardingError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response({"success": True, **result}, status=status.HTTP_201_CREATED)


class StockOverviewView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def get(self, request, seller_id):
    seller = _require_seller(request, seller_id)
    try:
      data = build_stock_overview(seller)
    except StockTransferError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response({"success": True, **data})


class StockTransferView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, seller_id):
    seller = _require_seller(request, seller_id)
    serializer = StockTransferSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    try:
      result = perform_stock_transfer(
        seller,
        product_id=serializer.validated_data["product_id"],
        from_warehouse_id=serializer.validated_data["from_warehouse_id"],
        to_warehouse_id=serializer.validated_data["to_warehouse_id"],
        quantity=serializer.validated_data["quantity"],
        user=request.user,
      )
    except StockTransferError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)


class StockTransferBulkView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, seller_id):
    seller = _require_seller(request, seller_id)
    serializer = StockTransferBulkSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    product_ids = serializer.validated_data.get("product_ids")
    if product_ids is not None and len(product_ids) == 0:
      product_ids = None
    try:
      result = transfer_stocks_bulk(
        seller,
        from_warehouse_id=serializer.validated_data["from_warehouse_id"],
        to_warehouse_id=serializer.validated_data["to_warehouse_id"],
        product_ids=product_ids,
        user=request.user,
      )
    except StockTransferError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)


class StockDistributeView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, seller_id):
    seller = _require_seller(request, seller_id)
    serializer = StockDistributeSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    product_ids = serializer.validated_data.get("product_ids")
    if product_ids is not None and len(product_ids) == 0:
      product_ids = None
    try:
      result = distribute_stocks_evenly_bulk(
        seller,
        product_ids=product_ids,
        user=request.user,
      )
    except StockTransferError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)


class StockFilePreviewView(APIView):
  """Предпросмотр импорта остатков из Excel (формат WB)."""
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, seller_id):
    seller = _require_seller(request, seller_id)
    upload = request.FILES.get("file")
    warehouse_id = request.data.get("warehouse_id")
    if not upload:
      return Response({"detail": "Загрузите файл Excel"}, status=status.HTTP_400_BAD_REQUEST)
    if not warehouse_id:
      return Response({"detail": "Укажите warehouse_id"}, status=status.HTTP_400_BAD_REQUEST)
    try:
      warehouse_id = int(warehouse_id)
    except (TypeError, ValueError):
      return Response({"detail": "Некорректный warehouse_id"}, status=status.HTTP_400_BAD_REQUEST)

    try:
      payload = build_stock_import_preview(
        seller,
        warehouse_id=warehouse_id,
        file_bytes=upload.read(),
      )
    except StockFileImportError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    return Response({"success": True, **payload})


class StockFileApplyView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, seller_id):
    seller = _require_seller(request, seller_id)
    serializer = StockFileApplySerializer(
      data=request.data,
      context={"seller_id": seller_id},
    )
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    try:
      result = apply_stock_import(
        seller,
        warehouse_id=data["warehouse_id"],
        rows=data["rows"],
        user=request.user,
      )
    except StockFileImportError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response({"success": result.get("ok", False), **result}, status=status.HTTP_201_CREATED)


class OzonStocksPushView(APIView):
  """Отправить остатки CRM на выбранный склад Ozon FBS."""
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, seller_id):
    seller = _require_seller(request, seller_id)
    warehouse_id = request.data.get("warehouse_id")
    try:
      warehouse_id = int(warehouse_id)
    except (TypeError, ValueError):
      return Response({"detail": "Выберите склад Ozon"}, status=status.HTTP_400_BAD_REQUEST)
    from .services.ozon_stocks import OzonStockError, push_ozon_crm_stocks

    try:
      result = push_ozon_crm_stocks(seller, warehouse_id, user=request.user)
    except OzonStockError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)
