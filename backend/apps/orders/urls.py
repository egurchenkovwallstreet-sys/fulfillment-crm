from django.urls import path

from .views import (
  OrderListView,
  OrderStatsView,
  OrderSyncView,
  PickListDetailView,
  PickListGenerateView,
  PickListListView,
)

urlpatterns = [
    path("", OrderListView.as_view(), name="order-list"),
    path("stats/", OrderStatsView.as_view(), name="order-stats"),
    path("sync/", OrderSyncView.as_view(), name="order-sync"),
    path("pick-lists/", PickListListView.as_view(), name="pick-list-list"),
    path("pick-lists/generate/", PickListGenerateView.as_view(), name="pick-list-generate"),
    path("pick-lists/<int:pk>/", PickListDetailView.as_view(), name="pick-list-detail"),
]
