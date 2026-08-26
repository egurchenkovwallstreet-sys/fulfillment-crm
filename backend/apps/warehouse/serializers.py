from rest_framework import serializers

from apps.sellers.models import Seller

from .models import Cell, Product, StockOperation


class SellerBriefSerializer(serializers.ModelSerializer):
  has_wb_token = serializers.SerializerMethodField()
  has_ozon_api = serializers.SerializerMethodField()

  class Meta:
    model = Seller
    fields = (
      "id",
      "company_name",
      "wb_enabled",
      "ozon_enabled",
      "has_wb_token",
      "has_ozon_api",
    )

  def get_has_wb_token(self, obj: Seller) -> bool:
    return bool(obj.wb_api_token_encrypted)

  def get_has_ozon_api(self, obj: Seller) -> bool:
    return bool(obj.ozon_client_id and obj.ozon_api_key_encrypted)


class CellSerializer(serializers.ModelSerializer):
  class Meta:
    model = Cell
    fields = ("id", "number", "is_occupied", "marketplace")


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
      "marketplace",
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
  wb_warehouse_id = serializers.IntegerField(required=False, allow_null=True)
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
    from apps.integrations.marketplace import OZON
    from apps.sellers.models import SellerWarehouse

    marketplace = self.context.get("marketplace") or "wb"
    if marketplace == OZON:
      return attrs

    seller_id = attrs["seller_id"]
    wh_id = attrs.get("wb_warehouse_id")
    if not wh_id:
      raise serializers.ValidationError({"wb_warehouse_id": "Укажите склад WB"})
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


class OnboardingPreviewSerializer(serializers.Serializer):
  catalog_mode = serializers.ChoiceField(
    choices=["all", "with_stock"],
    default="all",
  )
  warehouse_ids = serializers.ListField(
    child=serializers.IntegerField(),
    required=False,
    allow_empty=False,
  )

  def validate(self, attrs):
    seller_id = self.context.get("seller_id")
    warehouse_ids = attrs.get("warehouse_ids") or []
    if not warehouse_ids:
      raise serializers.ValidationError({
        "warehouse_ids": "Выберите хотя бы один FBS-склад",
      })
    from apps.sellers.models import SellerWarehouse

    found = SellerWarehouse.objects.filter(
      seller_id=seller_id,
      pk__in=warehouse_ids,
    ).count()
    if found != len(set(warehouse_ids)):
      raise serializers.ValidationError({
        "warehouse_ids": "Один или несколько складов не найдены у селлера",
      })
    return attrs


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


class StockDistributeSerializer(serializers.Serializer):
  product_ids = serializers.ListField(
    child=serializers.IntegerField(min_value=1),
    required=False,
    allow_empty=True,
  )


class StockFileApplySerializer(serializers.Serializer):
  warehouse_id = serializers.IntegerField()
  rows = serializers.ListField(child=serializers.DictField(), min_length=1)

  def validate(self, attrs):
    seller_id = self.context.get("seller_id")
    from apps.sellers.models import SellerWarehouse

    wh_id = attrs["warehouse_id"]
    if not SellerWarehouse.objects.filter(pk=wh_id, seller_id=seller_id).exists():
      raise serializers.ValidationError({
        "warehouse_id": "Склад WB не найден у этого селлера",
      })
    return attrs


class InventorySerializer(serializers.Serializer):
  seller_id = serializers.IntegerField()
  barcode = serializers.CharField(max_length=100)
  quantity = serializers.IntegerField(min_value=0)
  warehouse_ids = serializers.ListField(
    child=serializers.IntegerField(),
    required=False,
    allow_empty=True,
  )
  cell_mode = serializers.ChoiceField(choices=["auto", "manual"], default="auto")
  cell_id = serializers.IntegerField(required=False, allow_null=True)
  name = serializers.CharField(required=False, allow_blank=True, max_length=500)

  def validate_seller_id(self, value):
    if not Seller.objects.filter(pk=value, is_active=True).exists():
      raise serializers.ValidationError("Селлер не найден или неактивен")
    return value

  def validate(self, attrs):
    from apps.integrations.marketplace import OZON
    from apps.sellers.models import SellerWarehouse

    marketplace = self.context.get("marketplace") or "wb"
    if marketplace == OZON:
      attrs["warehouse_ids"] = []
      return attrs

    seller_id = attrs["seller_id"]
    warehouse_ids = list(dict.fromkeys(attrs.get("warehouse_ids") or []))
    attrs["warehouse_ids"] = warehouse_ids
    if not warehouse_ids:
      raise serializers.ValidationError({"warehouse_ids": "Выберите хотя бы один склад WB"})

    found = SellerWarehouse.objects.filter(
      seller_id=seller_id,
      pk__in=warehouse_ids,
      is_enabled=True,
    ).count()
    if found != len(warehouse_ids):
      raise serializers.ValidationError({
        "warehouse_ids": "Один или несколько складов не найдены или отключены",
      })
    return attrs
