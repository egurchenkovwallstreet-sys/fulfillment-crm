from rest_framework import serializers

from apps.sellers.models import Seller

from .models import Order, PickList, PickListItem


class OrderSerializer(serializers.ModelSerializer):
  seller_name = serializers.CharField(source="seller.company_name", read_only=True)
  cell_number = serializers.CharField(source="product.cell.number", read_only=True, default="")
  status_display = serializers.CharField(source="get_status_display", read_only=True)

  class Meta:
    model = Order
    fields = (
      "id",
      "wb_order_id",
      "barcode",
      "seller",
      "seller_name",
      "cell_number",
      "status",
      "status_display",
      "marking_bound",
      "created_at",
    )


class PickListItemSerializer(serializers.ModelSerializer):
  cell_number = serializers.CharField(source="cell.number", read_only=True)
  product_name = serializers.CharField(source="product.name", read_only=True)

  class Meta:
    model = PickListItem
    fields = (
      "id",
      "cell_number",
      "barcode",
      "product_name",
      "quantity",
      "picked_quantity",
    )


class PickListSerializer(serializers.ModelSerializer):
  seller_name = serializers.CharField(source="seller.company_name", read_only=True)
  items = PickListItemSerializer(many=True, read_only=True)
  items_count = serializers.SerializerMethodField()
  total_quantity = serializers.SerializerMethodField()

  class Meta:
    model = PickList
    fields = (
      "id",
      "seller",
      "seller_name",
      "is_completed",
      "created_at",
      "items",
      "items_count",
      "total_quantity",
    )

  def get_items_count(self, obj):
    return obj.items.count()

  def get_total_quantity(self, obj):
    return sum(item.quantity for item in obj.items.all())


class PickListBriefSerializer(serializers.ModelSerializer):
  seller_name = serializers.CharField(source="seller.company_name", read_only=True)
  items_count = serializers.SerializerMethodField()

  class Meta:
    model = PickList
    fields = (
      "id",
      "seller",
      "seller_name",
      "is_completed",
      "created_at",
      "items_count",
    )

  def get_items_count(self, obj):
    return obj.items.count()


class OrderSyncSerializer(serializers.Serializer):
  seller_id = serializers.IntegerField(required=False, allow_null=True)

  def validate_seller_id(self, value):
    if value is None:
      return value
    if not Seller.objects.filter(pk=value, is_active=True).exists():
      raise serializers.ValidationError("Селлер не найден или неактивен")
    return value


class PickListGenerateSerializer(serializers.Serializer):
  seller_id = serializers.IntegerField()

  def validate_seller_id(self, value):
    if not Seller.objects.filter(pk=value, is_active=True).exists():
      raise serializers.ValidationError("Селлер не найден или неактивен")
    return value
