from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Fulfillment
from apps.accounts.serializers import CustomTokenObtainPairSerializer, UserSerializer
from apps.accounts.tenant import unique_fulfillment_slug

User = get_user_model()


class FulfillmentRegisterSerializer(serializers.Serializer):
  fulfillment_name = serializers.CharField(max_length=255)
  username = serializers.CharField(max_length=150)
  password = serializers.CharField(min_length=8, write_only=True)
  email = serializers.EmailField(required=False, allow_blank=True)

  def validate_fulfillment_name(self, value):
    name = value.strip()
    if len(name) < 2:
      raise serializers.ValidationError("Укажите название фулфилмента")
    return name

  def validate_username(self, value):
    if User.objects.filter(username=value).exists():
      raise serializers.ValidationError("Это имя пользователя уже занято")
    return value


class FulfillmentRegisterView(APIView):
  """Регистрация нового фулфилмента + первого администратора."""

  permission_classes = [AllowAny]

  @transaction.atomic
  def post(self, request):
    serializer = FulfillmentRegisterSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    fulfillment = Fulfillment.objects.create(
      name=data["fulfillment_name"],
      slug=unique_fulfillment_slug(data["fulfillment_name"]),
    )
    user = User.objects.create_user(
      username=data["username"],
      password=data["password"],
      email=data.get("email") or "",
      role=User.Role.ADMIN,
      fulfillment=fulfillment,
    )

    refresh = CustomTokenObtainPairSerializer.get_token(user)
    return Response(
      {
        "access": str(refresh.access_token),
        "refresh": str(refresh),
        "user": UserSerializer(user).data,
        "fulfillment": {
          "id": fulfillment.id,
          "name": fulfillment.name,
          "slug": fulfillment.slug,
        },
      },
      status=status.HTTP_201_CREATED,
    )
