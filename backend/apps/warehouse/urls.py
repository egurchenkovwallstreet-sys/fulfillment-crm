from django.urls import path

from .views import (
  CellListView,
  IntakeHistoryView,
  IntakeLookupView,
  IntakeView,
  SellerListView,
)

urlpatterns = [
  path("sellers/", SellerListView.as_view(), name="warehouse_sellers"),
  path("cells/", CellListView.as_view(), name="warehouse_cells"),
  path("intake/lookup/", IntakeLookupView.as_view(), name="intake_lookup"),
  path("intake/", IntakeView.as_view(), name="intake"),
  path("intake/history/", IntakeHistoryView.as_view(), name="intake_history"),
]
