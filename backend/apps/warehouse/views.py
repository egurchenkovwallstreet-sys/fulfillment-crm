from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsManager
from apps.sellers.models import Seller

from .models import Cell, Product, StockOperation
from .serializers import (
  CellSerializer,
  IntakeSerializer,
  MoveCellSerializer,
  ProductSerializer,
  SellerBriefSerializer,
  StockOperationSerializer,
)
from .services.cell_label import build_cell_label_data
from .services.cell_move import CellMoveError, move_product_to_cell
from .services.cells import cells_queryset_ordered
from .services.intake import IntakeError, perform_intake
from .services.wb_stocks import WBStockError, fetch_wb_stock_for_barcode, get_seller_warehouse
from .services.marking_lookup import lookup_marking_for_barcode, refresh_product_marking
from .services.wb_product_sync import refresh_seller_products_from_wb


class SellerListView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def get(self, request):
    sellers = Seller.objects.filter(is_active=True).order_by("company_name")
    return Response(SellerBriefSerializer(sellers, many=True).data)


class CellListView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def get(self, request):
    free_only = request.query_params.get("free") == "1"
    cells = cells_queryset_ordered(Cell.objects.all())
    if free_only:
      cells = cells.filter(is_occupied=False)
    return Response(CellSerializer(cells, many=True).data)


class SellerProductsView(APIView):
  """Товары селлера по ячейкам — для печати этикеток и переноса."""
  permission_classes = [IsAuthenticated, IsManager]

  def get(self, request, seller_id):
    seller = get_object_or_404(Seller, pk=seller_id, is_active=True)
    products = (
      Product.objects.filter(seller=seller)
      .select_related("cell", "seller")
      .order_by("cell__number")
    )
    products = sorted(products, key=lambda p: int(p.cell.number) if p.cell.number.isdigit() else p.cell.number)
    return Response(ProductSerializer(products, many=True).data)


class SellerProductsRefreshView(APIView):
  """Подтянуть названия и маркировку всех товаров селлера из WB."""
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, seller_id):
    seller = get_object_or_404(Seller, pk=seller_id, is_active=True)
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
    product = get_object_or_404(
      Product.objects.select_related("cell", "seller"),
      pk=product_id,
    )
    return Response(build_cell_label_data(product))


class ProductMoveCellView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def post(self, request, product_id):
    serializer = MoveCellSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    product = get_object_or_404(
      Product.objects.select_related("cell", "seller"),
      pk=product_id,
    )
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

    seller = get_object_or_404(Seller, pk=seller_id, is_active=True)

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
      Product.objects.filter(seller_id=seller_id, barcode=barcode)
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

    marking = lookup_marking_for_barcode(
      Seller.objects.get(pk=seller_id),
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
    serializer = IntakeSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    seller = get_object_or_404(Seller, pk=data["seller_id"], is_active=True)

    try:
      result = perform_intake(
        seller=seller,
        barcode=data["barcode"],
        quantity=data.get("quantity", 0),
        user=request.user,
        wb_warehouse_id=data["wb_warehouse_id"],
        stock_mode=data.get("stock_mode", "intake"),
        verified_stock_match=data.get("verified_stock_match", False),
        cell_mode=data.get("cell_mode", "auto"),
        cell_id=data.get("cell_id"),
        name=data.get("name", ""),
      )
    except IntakeError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    qty = result.product.quantity
    if result.stock_mode == "sync_from_wb":
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


class IntakeHistoryView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def get(self, request):
    ops = (
      StockOperation.objects.filter(
        operation_type__in=[
          StockOperation.OperationType.INTAKE,
          StockOperation.OperationType.ADJUSTMENT,
        ],
      )
      .select_related("product", "product__cell", "product__seller")
      .order_by("-created_at")[:30]
    )
    return Response(StockOperationSerializer(ops, many=True).data)
