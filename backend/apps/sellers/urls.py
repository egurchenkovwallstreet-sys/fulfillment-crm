from django.urls import path

from .views import (
  SellerWarehouseListView,
  SellerWarehouseSyncView,
  SellerWarehouseToggleView,
)
from .views_cabinet import (
  SellerCabinetBarcodeView,
  SellerCabinetView,
  SellerInviteView,
  SellerManageListCreateView,
)

urlpatterns = [
  path("manage/", SellerManageListCreateView.as_view(), name="seller-manage-list"),
  path(
    "manage/<int:seller_id>/invite/",
    SellerInviteView.as_view(),
    name="seller-invite",
  ),
  path("cabinet/", SellerCabinetView.as_view(), name="seller-cabinet"),
  path(
    "cabinet/barcode/<str:barcode>/",
    SellerCabinetBarcodeView.as_view(),
    name="seller-cabinet-barcode",
  ),
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
