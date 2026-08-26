from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from .serializers import CustomTokenObtainPairSerializer, UserSerializer


class LoginView(TokenObtainPairView):
  serializer_class = CustomTokenObtainPairSerializer


class MeView(APIView):
  permission_classes = [IsAuthenticated]

  def get(self, request):
    user = request.user
    if user.seller_id:
      user = type(user).objects.select_related("seller").get(pk=user.pk)
    return Response(UserSerializer(user).data)
