from rest_framework import serializers

from apps.sellers.models import Seller

from .models import Cell, Product, StockOperation


class SellerBriefSerializer(serializers.ModelSerializer):
  class Meta:
    model = Seller
    fields = ("id", "company_name")


class CellSerializer(serializers.ModelSerializer):
  class Meta:
    model = Cell
    fields = ("id", "number", "is_occupied")


class ProductSerializer(serializers.ModelSerializer):
  cell_number = serializers.CharField(source="cell.number", read_only=True)
  seller_name = serializers.CharField(source="seller.company_name", read_only=True)

  class Meta:
    model = Product
    fields = (
      "id",
      "barcode",
      "name",
      "quantity",
      "cell",
      "cell_number",
      "seller",
      "seller_name",
      "requires_marking",
      "wb_nm_id",
      "vendor_code",
      "tech_size",
      "wb_size",
      "photo_url",
    )


class StockOperationSerializer(serializers.ModelSerializer):
  barcode = serializers.CharField(source="product.barcode", read_only=True)
  cell_number = serializers.CharField(source="product.cell.number", read_only=True)
  seller_name = serializers.CharField(source="product.seller.company_name", read_only=True)

  class Meta:
    model = StockOperation
    fields = (
      "id",
      "barcode",
      "cell_number",
      "seller_name",
      "operation_type",
      "quantity",
      "comment",
      "created_at",
    )


class IntakeSerializer(serializers.Serializer):
  seller_id = serializers.IntegerField()
  wb_warehouse_id = serializers.IntegerField()
  barcode = serializers.CharField(max_length=100)
  quantity = serializers.IntegerField(min_value=0, default=0)
  stock_mode = serializers.ChoiceField(
    choices=["intake", "sync_from_wb"],
    default="intake",
  )
  verified_stock_match = serializers.BooleanField(default=False)
  cell_mode = serializers.ChoiceField(choices=["auto", "manual"], default="auto")
  cell_id = serializers.IntegerField(required=False, allow_null=True)
  name = serializers.CharField(required=False, allow_blank=True, max_length=500)

  def validate_seller_id(self, value):
    if not Seller.objects.filter(pk=value, is_active=True).exists():
      raise serializers.ValidationError("Селлер не найден или неактивен")
    return value

  def validate(self, attrs):
    from apps.sellers.models import SellerWarehouse

    seller_id = attrs["seller_id"]
    wh_id = attrs["wb_warehouse_id"]
    if not SellerWarehouse.objects.filter(pk=wh_id, seller_id=seller_id).exists():
      raise serializers.ValidationError({"wb_warehouse_id": "Склад WB не найден у этого селлера"})

    stock_mode = attrs.get("stock_mode", "intake")
    if stock_mode == "sync_from_wb":
      if not attrs.get("verified_stock_match"):
        raise serializers.ValidationError({
          "verified_stock_match": (
            "Подтвердите, что на фулфилменте пересчитали остатки и они совпадают с ЛК WB"
          ),
        })
    elif attrs.get("quantity", 0) < 1:
      raise serializers.ValidationError({"quantity": "Укажите количество от 1"})

    return attrs


class MoveCellSerializer(serializers.Serializer):
  cell_id = serializers.IntegerField()

  def validate_cell_id(self, value):
    if not Cell.objects.filter(pk=value).exists():
      raise serializers.ValidationError("Ячейка не найдена")
    return value


class OnboardingExcludeSerializer(serializers.Serializer):
  items = serializers.ListField(child=serializers.DictField())
  exclude_barcodes = serializers.ListField(
    child=serializers.CharField(max_length=100),
    required=False,
    allow_empty=True,
  )
  exclude_nm_ids = serializers.ListField(
    child=serializers.IntegerField(),
    required=False,
    allow_empty=True,
  )


class OnboardingConfirmSerializer(serializers.Serializer):
  items = serializers.ListField(child=serializers.DictField(), min_length=1)


class StockTransferSerializer(serializers.Serializer):
  product_id = serializers.IntegerField()
  from_warehouse_id = serializers.IntegerField()
  to_warehouse_id = serializers.IntegerField()
  quantity = serializers.IntegerField(min_value=1)
