from django.contrib import admin

from .models import Seller, SellerOzonWarehouse, SellerWarehouse


class SellerWarehouseInline(admin.TabularInline):
  model = SellerWarehouse
  extra = 0
  fields = ("wb_warehouse_id", "name", "address", "office_id", "is_enabled", "synced_at")
  readonly_fields = ("wb_warehouse_id", "name", "address", "office_id", "synced_at")


class SellerOzonWarehouseInline(admin.TabularInline):
  model = SellerOzonWarehouse
  extra = 0
  fields = ("ozon_warehouse_id", "name", "is_rfbs", "is_enabled", "synced_at")
  readonly_fields = ("ozon_warehouse_id", "name", "is_rfbs", "synced_at")


@admin.register(Seller)
class SellerAdmin(admin.ModelAdmin):
  list_display = (
    "company_name",
    "is_active",
    "wb_enabled",
    "ozon_enabled",
    "wb_count_new",
    "wb_count_assembly",
    "wb_count_delivery",
  )
  list_filter = ("is_active", "wb_enabled", "ozon_enabled")
  search_fields = ("company_name",)
  inlines = [SellerWarehouseInline, SellerOzonWarehouseInline]


@admin.register(SellerWarehouse)
class SellerWarehouseAdmin(admin.ModelAdmin):
  list_display = ("seller", "wb_warehouse_id", "name", "is_enabled", "synced_at")
  list_filter = ("is_enabled", "seller")
  search_fields = ("name", "seller__company_name")


@admin.register(SellerOzonWarehouse)
class SellerOzonWarehouseAdmin(admin.ModelAdmin):
  list_display = ("seller", "ozon_warehouse_id", "name", "is_enabled", "synced_at")
  list_filter = ("is_enabled", "seller")
  search_fields = ("name", "seller__company_name")
