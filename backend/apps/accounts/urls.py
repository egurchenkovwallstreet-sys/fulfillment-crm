from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from apps.sellers.views_cabinet import SellerInvitePreviewView, SellerRegisterView

from .views import LoginView, MeView

urlpatterns = [
  path("login/", LoginView.as_view(), name="auth_login"),
  path("token/", LoginView.as_view(), name="token_obtain_pair"),
  path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
  path("me/", MeView.as_view(), name="auth_me"),
  path("invite/<uuid:token>/", SellerInvitePreviewView.as_view(), name="auth_invite_preview"),
  path("register/", SellerRegisterView.as_view(), name="auth_register"),
]
