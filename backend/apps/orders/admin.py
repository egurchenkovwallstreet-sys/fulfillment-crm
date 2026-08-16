from django.contrib import admin

from .models import Order, PickList, PickListItem, Supply


class PickListItemInline(admin.TabularInline):
  model = PickListItem
  extra = 0


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
  list_display = ("wb_order_id", "seller", "barcode", "status", "marking_bound")
  list_filter = ("status", "seller", "marking_bound")
  search_fields = ("wb_order_id", "barcode")


@admin.register(PickList)
class PickListAdmin(admin.ModelAdmin):
  list_display = ("id", "seller", "is_completed", "created_at")
  inlines = [PickListItemInline]


@admin.register(Supply)
class SupplyAdmin(admin.ModelAdmin):
  list_display = ("id", "seller", "status", "supply_barcode_printed", "stock_deducted")
  list_filter = ("status", "seller")
