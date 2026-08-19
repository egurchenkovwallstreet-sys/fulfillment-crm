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
      "has_sticker",
      "marking_bound",
      "created_at",
    )


class OrderAssemblySerializer(serializers.ModelSerializer):
  cell_number = serializers.CharField(source="product.cell.number", read_only=True, default="")
  status_display = serializers.CharField(source="get_status_display", read_only=True)
  wb_stage_display = serializers.SerializerMethodField()
  requires_marking = serializers.SerializerMethodField()
  can_send_to_assembly = serializers.SerializerMethodField()
  can_send_to_delivery = serializers.SerializerMethodField()

  class Meta:
    model = Order
    fields = (
      "id",
      "wb_order_id",
      "barcode",
      "cell_number",
      "status",
      "status_display",
      "wb_supplier_status",
      "wb_status",
      "wb_stage_display",
      "has_sticker",
      "sticker_part_a",
      "sticker_part_b",
      "marking_bound",
      "requires_marking",
      "can_send_to_assembly",
      "can_send_to_delivery",
      "created_at",
    )

  def get_wb_stage_display(self, obj):
    from apps.orders.services.assembly import get_wb_stage_label
    return get_wb_stage_label(obj.wb_supplier_status)

  def get_requires_marking(self, obj):
    from apps.warehouse.services.marking_lookup import resolve_product_requires_marking
    return resolve_product_requires_marking(obj.product, obj.barcode, obj.seller)

  def get_can_send_to_assembly(self, obj):
    from apps.orders.services.supply_flow import order_can_send_to_assembly
    return order_can_send_to_assembly(obj)

  def get_can_send_to_delivery(self, obj):
    from apps.orders.services.supply_flow import order_can_send_to_delivery
    return order_can_send_to_delivery(obj)


class OrderPrintSerializer(serializers.ModelSerializer):
  status_display = serializers.CharField(source="get_status_display", read_only=True)
  requires_marking = serializers.SerializerMethodField()
  marking_bound = serializers.BooleanField(read_only=True)
  can_send_to_delivery = serializers.SerializerMethodField()

  class Meta:
    model = Order
    fields = (
      "id",
      "wb_order_id",
      "barcode",
      "status",
      "status_display",
      "sticker_file",
      "sticker_part_a",
      "sticker_part_b",
      "has_sticker",
      "requires_marking",
      "marking_bound",
      "can_send_to_delivery",
    )

  def get_requires_marking(self, obj):
    from apps.warehouse.services.marking_lookup import resolve_product_requires_marking
    return resolve_product_requires_marking(obj.product, obj.barcode, obj.seller)

  def get_can_send_to_delivery(self, obj):
    from apps.orders.services.supply_flow import order_can_send_to_delivery
    return order_can_send_to_delivery(obj)


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


class SellerAssemblyCountersSerializer(serializers.Serializer):
  id = serializers.IntegerField()
  company_name = serializers.CharField()
  new = serializers.IntegerField()
  in_picking = serializers.IntegerField()
  in_delivery = serializers.IntegerField()
  assembled = serializers.IntegerField()
  label_printed = serializers.IntegerField()
  marked = serializers.IntegerField()
  in_supply = serializers.IntegerField()
  shipped = serializers.IntegerField()
  cancelled = serializers.IntegerField(required=False)
  total_active = serializers.IntegerField()


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


class ScanPrintSerializer(serializers.Serializer):
  barcode = serializers.CharField(max_length=200)


class BindMarkingSerializer(serializers.Serializer):
  order_id = serializers.IntegerField()
  marking_code = serializers.CharField(max_length=500)


class ReplaceOrderSerializer(serializers.Serializer):
  order_id = serializers.IntegerField()


class OrderActionSerializer(serializers.Serializer):
  order_id = serializers.IntegerField()
