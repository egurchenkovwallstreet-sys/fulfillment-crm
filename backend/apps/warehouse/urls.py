from django.urls import path

from .views import (
  CellListView,
  IntakeHistoryView,
  IntakeLookupView,
  IntakeView,
  ProductCellLabelView,
  ProductMoveCellView,
  SellerListView,
  SellerProductsRefreshView,
  SellerProductsView,
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
  path("products/<int:product_id>/cell-label/", ProductCellLabelView.as_view(), name="product_cell_label"),
  path("products/<int:product_id>/move-cell/", ProductMoveCellView.as_view(), name="product_move_cell"),
  path("intake/lookup/", IntakeLookupView.as_view(), name="intake_lookup"),
  path("intake/", IntakeView.as_view(), name="intake"),
  path("intake/history/", IntakeHistoryView.as_view(), name="intake_history"),
]
