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
  ProductSerializer,
  SellerBriefSerializer,
  StockOperationSerializer,
)
from .services.cells import cells_queryset_ordered
from .services.intake import IntakeError, perform_intake
from .services.marking_lookup import lookup_marking_for_barcode, refresh_product_marking


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


class IntakeLookupView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def get(self, request):
    barcode = request.query_params.get("barcode", "").strip()
    seller_id = request.query_params.get("seller_id")

    if not barcode or not seller_id:
      return Response(
        {"detail": "Укажите barcode и seller_id"},
        status=status.HTTP_400_BAD_REQUEST,
      )

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
      product = perform_intake(
        seller=seller,
        barcode=data["barcode"],
        quantity=data["quantity"],
        user=request.user,
        cell_mode=data.get("cell_mode", "auto"),
        cell_id=data.get("cell_id"),
        name=data.get("name", ""),
      )
    except IntakeError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    return Response(
      {
        "success": True,
        "message": f"Принято {data['quantity']} шт.",
        "product": ProductSerializer(product).data,
      },
      status=status.HTTP_201_CREATED,
    )


class IntakeHistoryView(APIView):
  permission_classes = [IsAuthenticated, IsManager]

  def get(self, request):
    ops = (
      StockOperation.objects.filter(operation_type=StockOperation.OperationType.INTAKE)
      .select_related("product", "product__cell", "product__seller")
      .order_by("-created_at")[:30]
    )
    return Response(StockOperationSerializer(ops, many=True).data)
