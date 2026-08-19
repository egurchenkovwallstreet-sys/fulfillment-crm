from django.contrib import admin
from django.urls import include, path

import config.admin  # noqa: F401 — заголовки админки
from apps.orders.views_health import HealthView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", HealthView.as_view(), name="health"),
    path("api/auth/", include("apps.accounts.urls")),
    path("api/sellers/", include("apps.sellers.urls")),
    path("api/warehouse/", include("apps.warehouse.urls")),
    path("api/orders/", include("apps.orders.urls")),
    path("api/integrations/", include("apps.integrations.urls")),
]
