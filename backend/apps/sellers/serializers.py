from rest_framework import serializers

from django.core.exceptions import ObjectDoesNotExist

from apps.sellers.models import Seller, SellerWarehouse
from apps.sellers.utils import seller_has_user_account, seller_username


class SellerWarehouseSerializer(serializers.ModelSerializer):
  class Meta:
    model = SellerWarehouse
    fields = (
      "id",
      "wb_warehouse_id",
      "name",
      "address",
      "office_id",
      "is_enabled",
      "synced_at",
    )
    read_only_fields = (
      "id",
      "wb_warehouse_id",
      "name",
      "address",
      "office_id",
      "synced_at",
    )


class SellerWarehouseToggleSerializer(serializers.Serializer):
  is_enabled = serializers.BooleanField()


class SellerManageSerializer(serializers.ModelSerializer):
  has_account = serializers.SerializerMethodField()
  invite_token = serializers.SerializerMethodField()
  username = serializers.SerializerMethodField()
  has_wb_token = serializers.SerializerMethodField()
  has_ozon_api = serializers.SerializerMethodField()

  class Meta:
    model = Seller
    fields = (
      "id",
      "company_name",
      "is_active",
      "has_account",
      "username",
      "invite_token",
      "wb_enabled",
      "ozon_enabled",
      "has_wb_token",
      "has_ozon_api",
      "ozon_client_id",
      "wb_count_new",
      "wb_count_assembly",
      "wb_count_delivery",
      "ozon_count_new",
      "ozon_count_assembly",
      "ozon_count_delivery",
      "created_at",
    )
    read_only_fields = (
      "id",
      "has_account",
      "username",
      "invite_token",
      "has_wb_token",
      "has_ozon_api",
      "ozon_client_id",
      "wb_count_new",
      "wb_count_assembly",
      "wb_count_delivery",
      "ozon_count_new",
      "ozon_count_assembly",
      "ozon_count_delivery",
      "created_at",
    )

  def get_has_account(self, obj: Seller) -> bool:
    return seller_has_user_account(obj)

  def get_username(self, obj: Seller) -> str | None:
    return seller_username(obj)

  def get_invite_token(self, obj: Seller) -> str | None:
    try:
      invite = obj.invite
    except ObjectDoesNotExist:
      return None
    if invite.is_active:
      return str(invite.token)
    return None

  def get_has_wb_token(self, obj: Seller) -> bool:
    return bool(obj.wb_api_token_encrypted)

  def get_has_ozon_api(self, obj: Seller) -> bool:
    return bool(obj.ozon_client_id and obj.ozon_api_key_encrypted)


class SellerCreateSerializer(serializers.ModelSerializer):
  wb_enabled = serializers.BooleanField(default=True)
  ozon_enabled = serializers.BooleanField(default=False)

  class Meta:
    model = Seller
    fields = ("company_name", "is_active", "wb_enabled", "ozon_enabled")

  def validate(self, attrs):
    if not attrs.get("wb_enabled", True) and not attrs.get("ozon_enabled", False):
      raise serializers.ValidationError("Выберите хотя бы один маркетплейс: WB или Ozon")
    return attrs

  def create(self, validated_data):
    from apps.sellers.services.invite import ensure_seller_invite

    seller = super().create(validated_data)
    ensure_seller_invite(seller)
    return seller


class SellerInviteSerializer(serializers.Serializer):
  token = serializers.UUIDField()
  invite_path = serializers.CharField()
  has_account = serializers.BooleanField()
  company_name = serializers.CharField()


class SellerRegisterSerializer(serializers.Serializer):
  token = serializers.UUIDField()
  username = serializers.CharField(max_length=150)
  password = serializers.CharField(min_length=8, write_only=True)
  email = serializers.EmailField(required=False, allow_blank=True)

  def validate_username(self, value):
    from django.contrib.auth import get_user_model

    if get_user_model().objects.filter(username=value).exists():
      raise serializers.ValidationError("Это имя пользователя уже занято")
    return value


class SellerPeriodMetricSerializer(serializers.Serializer):
  current = serializers.IntegerField()
  previous = serializers.IntegerField()
  change_pct = serializers.FloatField(allow_null=True)
  direction = serializers.CharField()


class SellerCabinetSummarySerializer(serializers.Serializer):
  orders_day = SellerPeriodMetricSerializer()
  orders_week = SellerPeriodMetricSerializer()
  orders_month = SellerPeriodMetricSerializer()
  sku_count = serializers.IntegerField()
  total_stock = serializers.IntegerField()


class SellerWbStageCountsSerializer(serializers.Serializer):
  new = serializers.IntegerField()
  in_picking = serializers.IntegerField()
  in_delivery = serializers.IntegerField()


class SellerWeeklyShipmentDaySerializer(serializers.Serializer):
  date = serializers.DateField()
  weekday = serializers.CharField()
  orders = serializers.IntegerField()
  amount = serializers.DecimalField(max_digits=12, decimal_places=2)


class SellerWeeklyShipmentWeekSerializer(serializers.Serializer):
  week_start = serializers.DateField()
  week_end = serializers.DateField()
  total = serializers.IntegerField()
  total_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
  supplies_count = serializers.IntegerField()
  is_current = serializers.BooleanField()
  days = SellerWeeklyShipmentDaySerializer(many=True)


class SellerWeeklyShipmentsSerializer(serializers.Serializer):
  today = serializers.DateField()
  weeks = SellerWeeklyShipmentWeekSerializer(many=True)


class AdminBillingSellerSerializer(serializers.Serializer):
  seller_id = serializers.IntegerField()
  company_name = serializers.CharField()
  weekly_shipments = SellerWeeklyShipmentsSerializer(allow_null=True)
  error = serializers.CharField(allow_null=True)


class AdminBillingDashboardSerializer(serializers.Serializer):
  today = serializers.DateField()
  combined = SellerWeeklyShipmentsSerializer()
  sellers = AdminBillingSellerSerializer(many=True)


class SellerBarcodeAnalyticsSerializer(serializers.Serializer):
  barcode = serializers.CharField()
  name = serializers.CharField()
  tech_size = serializers.CharField(allow_blank=True)
  photo_url = serializers.URLField(allow_blank=True)
  stock_quantity = serializers.IntegerField()
  orders_day = serializers.IntegerField()
  orders_week = serializers.IntegerField()
  orders_month = serializers.IntegerField()
  avg_daily_sales = serializers.FloatField()
  days_remaining = serializers.FloatField(allow_null=True)
  stock_level = serializers.CharField()


class SellerBarcodeDetailSerializer(SellerBarcodeAnalyticsSerializer):
  daily_orders = serializers.ListField()
  sales_lookback_days = serializers.IntegerField()
