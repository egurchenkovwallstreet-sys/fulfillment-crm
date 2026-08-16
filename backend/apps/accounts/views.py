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
    return Response(UserSerializer(request.user).data)
