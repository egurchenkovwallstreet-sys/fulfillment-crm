from django.urls import path

from .views import (
  AssemblyBindMarkingView,
  AssemblyReplaceOrderView,
  AssemblyScanPrintView,
  AssemblySendToAssemblyView,
  AssemblySendToDeliveryView,
  AssemblySellerDetailView,
  AssemblySellerListView,
  AssemblyStartView,
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
    path("assembly/sellers/", AssemblySellerListView.as_view(), name="assembly-seller-list"),
    path(
      "assembly/sellers/<int:seller_id>/",
      AssemblySellerDetailView.as_view(),
      name="assembly-seller-detail",
    ),
    path(
      "assembly/sellers/<int:seller_id>/start/",
      AssemblyStartView.as_view(),
      name="assembly-start",
    ),
    path(
      "assembly/sellers/<int:seller_id>/scan-print/",
      AssemblyScanPrintView.as_view(),
      name="assembly-scan-print",
    ),
    path(
      "assembly/sellers/<int:seller_id>/bind-marking/",
      AssemblyBindMarkingView.as_view(),
      name="assembly-bind-marking",
    ),
    path(
      "assembly/sellers/<int:seller_id>/replace-order/",
      AssemblyReplaceOrderView.as_view(),
      name="assembly-replace-order",
    ),
    path(
      "assembly/sellers/<int:seller_id>/send-to-assembly/",
      AssemblySendToAssemblyView.as_view(),
      name="assembly-send-to-assembly",
    ),
    path(
      "assembly/sellers/<int:seller_id>/send-to-delivery/",
      AssemblySendToDeliveryView.as_view(),
      name="assembly-send-to-delivery",
    ),
]
