from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from apps.accounts.tenant import get_user_fulfillment

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
  role_display = serializers.CharField(source="get_role_display", read_only=True)
  seller_name = serializers.SerializerMethodField()
  fulfillment_id = serializers.SerializerMethodField()
  fulfillment_name = serializers.SerializerMethodField()
  wb_enabled = serializers.SerializerMethodField()
  ozon_enabled = serializers.SerializerMethodField()
  has_wb_token = serializers.SerializerMethodField()
  has_ozon_api = serializers.SerializerMethodField()

  class Meta:
    model = User
    fields = (
      "id",
      "username",
      "email",
      "first_name",
      "last_name",
      "role",
      "role_display",
      "fulfillment_id",
      "fulfillment_name",
      "seller",
      "seller_name",
      "wb_enabled",
      "ozon_enabled",
      "has_wb_token",
      "has_ozon_api",
    )
    read_only_fields = fields

  def get_seller_name(self, obj):
    if obj.seller_id:
      return obj.seller.company_name
    return None

  def get_fulfillment_id(self, obj):
    fulfillment = get_user_fulfillment(obj)
    return fulfillment.id if fulfillment else None

  def get_fulfillment_name(self, obj):
    fulfillment = get_user_fulfillment(obj)
    return fulfillment.name if fulfillment else None

  def _seller(self, obj):
    return obj.seller if obj.seller_id else None

  def get_wb_enabled(self, obj):
    seller = self._seller(obj)
    if obj.role == "seller":
      return bool(seller and seller.wb_enabled)
    return True

  def get_ozon_enabled(self, obj):
    seller = self._seller(obj)
    if obj.role == "seller":
      return bool(seller and seller.ozon_enabled)
    return True

  def get_has_wb_token(self, obj):
    seller = self._seller(obj)
    return bool(seller and seller.wb_api_token_encrypted)

  def get_has_ozon_api(self, obj):
    seller = self._seller(obj)
    return bool(seller and seller.ozon_client_id and seller.ozon_api_key_encrypted)


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
  @classmethod
  def get_token(cls, user):
    token = super().get_token(user)
    token["role"] = user.role
    if user.seller_id:
      token["seller_id"] = user.seller_id
    fulfillment = get_user_fulfillment(user)
    if fulfillment:
      token["fulfillment_id"] = fulfillment.id
    return token

  def validate(self, attrs):
    data = super().validate(attrs)
    data["user"] = UserSerializer(self.user).data
    return data
