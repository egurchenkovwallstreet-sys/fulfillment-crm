from django.contrib import admin

from .models import Cell, PriceGroup, Product, StockOperation


@admin.register(PriceGroup)
class PriceGroupAdmin(admin.ModelAdmin):
  list_display = ("name", "processing_price", "sort_order")


@admin.register(Cell)
class CellAdmin(admin.ModelAdmin):
  list_display = ("number", "is_occupied", "created_at")
  search_fields = ("number",)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
  list_display = ("barcode", "seller", "cell", "quantity", "requires_marking")
  list_filter = ("seller", "requires_marking")
  search_fields = ("barcode", "name")


@admin.register(StockOperation)
class StockOperationAdmin(admin.ModelAdmin):
  list_display = ("product", "operation_type", "quantity", "created_at")
  list_filter = ("operation_type",)
