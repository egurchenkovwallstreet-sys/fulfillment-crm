from django.urls import path

from .views import (
  SellerWarehouseListView,
  SellerWarehouseSyncView,
  SellerWarehouseToggleView,
)
from .views_ozon import (
  SellerMarketplaceFlagsView,
  SellerOzonKeysView,
  SellerOzonWarehouseListView,
  SellerOzonWarehouseSyncView,
  SellerOzonWarehouseToggleView,
)
from .views_cabinet import (
  AdminBillingDashboardView,
  SellerCabinetBarcodeView,
  SellerCabinetView,
  SellerInviteView,
  SellerManageDetailView,
  SellerManageListCreateView,
  SellerWbTokenView,
)

urlpatterns = [
  path("manage/", SellerManageListCreateView.as_view(), name="seller-manage-list"),
  path(
    "manage/<int:seller_id>/",
    SellerManageDetailView.as_view(),
    name="seller-manage-detail",
  ),
  path(
    "manage/<int:seller_id>/wb-token/",
    SellerWbTokenView.as_view(),
    name="seller-wb-token",
  ),
  path(
    "admin/billing/",
    AdminBillingDashboardView.as_view(),
    name="admin-billing-dashboard",
  ),
  path(
    "manage/<int:seller_id>/invite/",
    SellerInviteView.as_view(),
    name="seller-invite",
  ),
  path(
    "manage/<int:seller_id>/marketplaces/",
    SellerMarketplaceFlagsView.as_view(),
    name="seller-marketplaces",
  ),
  path(
    "manage/<int:seller_id>/ozon-keys/",
    SellerOzonKeysView.as_view(),
    name="seller-ozon-keys",
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
  path(
    "<int:seller_id>/ozon-warehouses/",
    SellerOzonWarehouseListView.as_view(),
    name="seller-ozon-warehouse-list",
  ),
  path(
    "<int:seller_id>/ozon-warehouses/sync/",
    SellerOzonWarehouseSyncView.as_view(),
    name="seller-ozon-warehouse-sync",
  ),
  path(
    "<int:seller_id>/ozon-warehouses/<int:warehouse_id>/",
    SellerOzonWarehouseToggleView.as_view(),
    name="seller-ozon-warehouse-toggle",
  ),
]
