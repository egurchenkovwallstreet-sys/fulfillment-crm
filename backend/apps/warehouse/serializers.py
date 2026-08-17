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
  barcode = serializers.CharField(max_length=100)
  quantity = serializers.IntegerField(min_value=1)
  cell_mode = serializers.ChoiceField(choices=["auto", "manual"], default="auto")
  cell_id = serializers.IntegerField(required=False, allow_null=True)
  name = serializers.CharField(required=False, allow_blank=True, max_length=500)

  def validate_seller_id(self, value):
    if not Seller.objects.filter(pk=value, is_active=True).exists():
      raise serializers.ValidationError("Селлер не найден или неактивен")
    return value
