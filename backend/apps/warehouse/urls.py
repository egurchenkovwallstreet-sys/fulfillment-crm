from django.urls import path

from .views import (
  CellListView,
  IntakeHistoryView,
  IntakeLookupView,
  IntakeView,
  InventoryLookupView,
  InventoryView,
  OnboardingConfirmView,
  OnboardingExcludeView,
  OnboardingPreviewView,
  ProductCellLabelView,
  ProductMoveCellView,
  SellerListView,
  SellerProductsRefreshView,
  SellerProductsView,
  StockFileApplyView,
  StockFilePreviewView,
  StockOverviewView,
  StockTransferView,
  StockDistributeView,
)
from .views_pricing import PriceGroupListView, SellerPricingView

urlpatterns = [
  path("sellers/", SellerListView.as_view(), name="warehouse_sellers"),
  path("sellers/<int:seller_id>/products/", SellerProductsView.as_view(), name="warehouse_seller_products"),
  path(
    "sellers/<int:seller_id>/products/refresh-from-wb/",
    SellerProductsRefreshView.as_view(),
    name="warehouse_seller_products_refresh",
  ),
  path("cells/", CellListView.as_view(), name="warehouse_cells"),
  path("products/<int:product_id>/cell-label/", ProductCellLabelView.as_view(), name="product_cell_label"),
  path("products/<int:product_id>/move-cell/", ProductMoveCellView.as_view(), name="product_move_cell"),
  path("intake/lookup/", IntakeLookupView.as_view(), name="intake_lookup"),
  path("intake/", IntakeView.as_view(), name="intake"),
  path("intake/history/", IntakeHistoryView.as_view(), name="intake_history"),
  path("inventory/lookup/", InventoryLookupView.as_view(), name="inventory_lookup"),
  path("inventory/", InventoryView.as_view(), name="inventory"),
  path(
    "onboarding/<int:seller_id>/preview/",
    OnboardingPreviewView.as_view(),
    name="onboarding_preview",
  ),
  path(
    "onboarding/<int:seller_id>/exclude/",
    OnboardingExcludeView.as_view(),
    name="onboarding_exclude",
  ),
  path(
    "onboarding/<int:seller_id>/confirm/",
    OnboardingConfirmView.as_view(),
    name="onboarding_confirm",
  ),
  path(
    "stock-import/<int:seller_id>/preview/",
    StockFilePreviewView.as_view(),
    name="stock_file_preview",
  ),
  path(
    "stock-import/<int:seller_id>/apply/",
    StockFileApplyView.as_view(),
    name="stock_file_apply",
  ),
  path(
    "sellers/<int:seller_id>/stock-overview/",
    StockOverviewView.as_view(),
    name="stock_overview",
  ),
  path(
    "sellers/<int:seller_id>/stock-transfer/",
    StockTransferView.as_view(),
    name="stock_transfer",
  ),
  path(
    "sellers/<int:seller_id>/stock-distribute/",
    StockDistributeView.as_view(),
    name="stock_distribute",
  ),
  path("price-groups/", PriceGroupListView.as_view(), name="price_groups"),
  path(
    "sellers/<int:seller_id>/pricing/",
    SellerPricingView.as_view(),
    name="seller_pricing",
  ),
]
