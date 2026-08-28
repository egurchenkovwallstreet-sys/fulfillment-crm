from django.contrib.auth import get_user_model
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsAdmin
from apps.accounts.serializers import UserSerializer
from apps.accounts.tenant import fulfillment_for_staff_user

User = get_user_model()


class StaffUserSerializer(serializers.ModelSerializer):
  role_display = serializers.CharField(source="get_role_display", read_only=True)

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
      "is_active",
      "date_joined",
      "last_login",
    )
    read_only_fields = fields


class StaffUserCreateSerializer(serializers.Serializer):
  username = serializers.CharField(max_length=150)
  password = serializers.CharField(min_length=8, write_only=True)
  email = serializers.EmailField(required=False, allow_blank=True)
  first_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
  last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)

  def validate_username(self, value):
    if User.objects.filter(username=value).exists():
      raise serializers.ValidationError("Это имя пользователя уже занято")
    return value


class StaffUserUpdateSerializer(serializers.Serializer):
  is_active = serializers.BooleanField(required=False)
  password = serializers.CharField(min_length=8, required=False, write_only=True)
  email = serializers.EmailField(required=False, allow_blank=True)
  first_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
  last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)


class StaffUserListCreateView(APIView):
  permission_classes = [IsAuthenticated, IsAdmin]

  def get(self, request):
    fulfillment = fulfillment_for_staff_user(request.user)
    if not fulfillment:
      return Response([], status=status.HTTP_200_OK)
    users = User.objects.filter(role=User.Role.MANAGER, fulfillment=fulfillment).order_by("username")
    return Response(StaffUserSerializer(users, many=True).data)

  def post(self, request):
    serializer = StaffUserCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    fulfillment = fulfillment_for_staff_user(request.user)
    if not fulfillment:
      return Response({"detail": "Фулфилмент не определён"}, status=status.HTTP_400_BAD_REQUEST)
    user = User.objects.create_user(
      username=data["username"],
      password=data["password"],
      email=data.get("email") or "",
      first_name=data.get("first_name") or "",
      last_name=data.get("last_name") or "",
      role=User.Role.MANAGER,
      fulfillment=fulfillment,
    )
    return Response(StaffUserSerializer(user).data, status=status.HTTP_201_CREATED)


class StaffUserDetailView(APIView):
  permission_classes = [IsAuthenticated, IsAdmin]

  def _get_manager(self, user_id: int, fulfillment):
    return User.objects.filter(pk=user_id, role=User.Role.MANAGER, fulfillment=fulfillment).first()

  def patch(self, request, user_id):
    fulfillment = fulfillment_for_staff_user(request.user)
    if not fulfillment:
      return Response(status=status.HTTP_404_NOT_FOUND)
    user = self._get_manager(user_id, fulfillment)
    if not user:
      return Response(status=status.HTTP_404_NOT_FOUND)

    serializer = StaffUserUpdateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    if "is_active" in data:
      user.is_active = data["is_active"]
    if "email" in data:
      user.email = data["email"]
    if "first_name" in data:
      user.first_name = data["first_name"]
    if "last_name" in data:
      user.last_name = data["last_name"]
    if "password" in data:
      user.set_password(data["password"])

    user.save()
    return Response(StaffUserSerializer(user).data)
