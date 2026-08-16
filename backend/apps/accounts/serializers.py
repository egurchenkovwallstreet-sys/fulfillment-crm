from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
  role_display = serializers.CharField(source="get_role_display", read_only=True)
  seller_name = serializers.SerializerMethodField()

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
      "seller",
      "seller_name",
    )
    read_only_fields = fields

  def get_seller_name(self, obj):
    if obj.seller_id:
      return obj.seller.company_name
    return None


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
  @classmethod
  def get_token(cls, user):
    token = super().get_token(user)
    token["role"] = user.role
    if user.seller_id:
      token["seller_id"] = user.seller_id
    return token

  def validate(self, attrs):
    data = super().validate(attrs)
    data["user"] = UserSerializer(self.user).data
    return data
