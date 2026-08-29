from django.urls import path

from .views import (
  CellListView,
  CellDetailView,
  IntakeHistoryView,
  IntakeLookupView,
  IntakeView,
  WbSyncIntakeAutoView,
  WbSyncIntakePreviewView,
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
  OzonStocksPushView,
)
from .views_pricing import PriceGroupDetailView, PriceGroupListView, SellerPricingView
from .views_xl_intake import (
  XlIntakeCompleteView,
  XlIntakeConnectWbView,
  XlIntakeExcelView,
  XlIntakeSaveView,
  XlIntakeScanView,
  XlIntakeSessionDetailView,
  XlIntakeSessionListCreateView,
)
from .views_article_intake import (
  ArticleIntakeCompleteView,
  ArticleIntakeConfirmGroupView,
  ArticleIntakePushView,
  ArticleIntakeScanView,
  ArticleIntakeSessionDetailView,
  ArticleIntakeSessionListCreateView,
)

urlpatterns = [
  path("sellers/", SellerListView.as_view(), name="warehouse_sellers"),
  path("sellers/<int:seller_id>/products/", SellerProductsView.as_view(), name="warehouse_seller_products"),
  path(
    "sellers/<int:seller_id>/products/refresh-from-wb/",
    SellerProductsRefreshView.as_view(),
    name="warehouse_seller_products_refresh",
  ),
  path("cells/", CellListView.as_view(), name="warehouse_cells"),
  path(
    "sellers/<int:seller_id>/cells/<str:cell_number>/",
    CellDetailView.as_view(),
    name="warehouse_cell_detail",
  ),
  path("products/<int:product_id>/cell-label/", ProductCellLabelView.as_view(), name="product_cell_label"),
  path("products/<int:product_id>/move-cell/", ProductMoveCellView.as_view(), name="product_move_cell"),
  path("intake/lookup/", IntakeLookupView.as_view(), name="intake_lookup"),
  path("intake/", IntakeView.as_view(), name="intake"),
  path("intake/wb-sync/preview/", WbSyncIntakePreviewView.as_view(), name="intake_wb_sync_preview"),
  path("intake/wb-sync/auto/", WbSyncIntakeAutoView.as_view(), name="intake_wb_sync_auto"),
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
  path(
    "sellers/<int:seller_id>/ozon-stocks/",
    OzonStocksPushView.as_view(),
    name="ozon_stocks_push",
  ),
  path("xl-intake/sessions/", XlIntakeSessionListCreateView.as_view(), name="xl_intake_sessions"),
  path(
    "xl-intake/sessions/<int:session_id>/",
    XlIntakeSessionDetailView.as_view(),
    name="xl_intake_session_detail",
  ),
  path(
    "xl-intake/sessions/<int:session_id>/scan/",
    XlIntakeScanView.as_view(),
    name="xl_intake_scan",
  ),
  path(
    "xl-intake/sessions/<int:session_id>/save/",
    XlIntakeSaveView.as_view(),
    name="xl_intake_save",
  ),
  path(
    "xl-intake/sessions/<int:session_id>/excel/",
    XlIntakeExcelView.as_view(),
    name="xl_intake_excel",
  ),
  path(
    "xl-intake/sessions/<int:session_id>/connect-wb/",
    XlIntakeConnectWbView.as_view(),
    name="xl_intake_connect_wb",
  ),
  path(
    "xl-intake/sessions/<int:session_id>/complete/",
    XlIntakeCompleteView.as_view(),
    name="xl_intake_complete",
  ),
  path(
    "article-intake/sessions/",
    ArticleIntakeSessionListCreateView.as_view(),
    name="article_intake_sessions",
  ),
  path(
    "article-intake/sessions/<int:session_id>/",
    ArticleIntakeSessionDetailView.as_view(),
    name="article_intake_session_detail",
  ),
  path(
    "article-intake/sessions/<int:session_id>/scan/",
    ArticleIntakeScanView.as_view(),
    name="article_intake_scan",
  ),
  path(
    "article-intake/sessions/<int:session_id>/confirm-group/",
    ArticleIntakeConfirmGroupView.as_view(),
    name="article_intake_confirm_group",
  ),
  path(
    "article-intake/sessions/<int:session_id>/push-marketplace/",
    ArticleIntakePushView.as_view(),
    name="article_intake_push",
  ),
  path(
    "article-intake/sessions/<int:session_id>/complete/",
    ArticleIntakeCompleteView.as_view(),
    name="article_intake_complete",
  ),
  path("price-groups/", PriceGroupListView.as_view(), name="price_groups"),
  path(
    "price-groups/<int:group_id>/",
    PriceGroupDetailView.as_view(),
    name="price_group_detail",
  ),
  path(
    "sellers/<int:seller_id>/pricing/",
    SellerPricingView.as_view(),
    name="seller_pricing",
  ),
]
