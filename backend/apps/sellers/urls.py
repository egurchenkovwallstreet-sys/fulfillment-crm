from django.urls import path

from .views import (
  SellerWarehouseListView,
  SellerWarehouseSyncView,
  SellerWarehouseToggleView,
)

urlpatterns = [
  path(
    "<int:seller_id>/warehouses/",
    SellerWarehouseListView.as_view(),
    name="seller-warehouse-list",
  ),
  path(
    "<int:seller_id>/warehouses/sync/",
    SellerWarehouseSyncView.as_view(),
    name="seller-warehouse-sync",
  ),
  path(
    "<int:seller_id>/warehouses/<int:warehouse_id>/",
    SellerWarehouseToggleView.as_view(),
    name="seller-warehouse-toggle",
  ),
]
