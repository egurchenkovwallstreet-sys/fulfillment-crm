from django.contrib import admin, messages

from .models import Cell, PriceGroup, Product, StockOperation
from .services.cell_delete import force_delete_cells


@admin.register(PriceGroup)
class PriceGroupAdmin(admin.ModelAdmin):
  list_display = ("name", "processing_price", "sort_order")


@admin.action(description="Удалить выбранные ячейки вместе с товарами")
def admin_force_delete_cells(modeladmin, request, queryset):
  stats = force_delete_cells(queryset)
  modeladmin.message_user(
    request,
    (
      f"Удалено ячеек: {stats['cells']}, товаров: {stats['products']}, "
      f"позиций листов подбора: {stats['pick_list_items']}, "
      f"заказов (снята привязка): {stats['orders_unlinked']}."
    ),
    messages.SUCCESS,
  )


@admin.register(Cell)
class CellAdmin(admin.ModelAdmin):
  list_display = ("seller", "number", "is_occupied", "created_at")
  list_filter = ("seller", "is_occupied")
  search_fields = ("number", "seller__company_name")
  actions = [admin_force_delete_cells]

  def get_deleted_objects(self, objs, request):
    cell_ids = [obj.pk for obj in objs]
    products = list(
      Product.objects.filter(cell_id__in=cell_ids).values_list("barcode", "seller__company_name"),
    )
    deleted = [str(obj) for obj in objs]
    deleted.extend(f"Товар {barcode} ({seller})" for barcode, seller in products)
    return deleted, {Cell._meta.label: len(objs)}, set(), set()

  def delete_queryset(self, request, queryset):
    stats = force_delete_cells(queryset)
    self.message_user(
      request,
      (
        f"Удалено ячеек: {stats['cells']}, товаров: {stats['products']}, "
        f"позиций листов подбора: {stats['pick_list_items']}."
      ),
      messages.SUCCESS,
    )

  def delete_model(self, request, obj):
    stats = force_delete_cells(Cell.objects.filter(pk=obj.pk))
    self.message_user(
      request,
      f"Ячейка №{obj.number} удалена (товаров: {stats['products']}).",
      messages.SUCCESS,
    )


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
  list_display = ("barcode", "seller", "cell", "quantity", "requires_marking")
  list_filter = ("seller", "requires_marking")
  search_fields = ("barcode", "name")


@admin.register(StockOperation)
class StockOperationAdmin(admin.ModelAdmin):
  list_display = ("product", "operation_type", "quantity", "created_at")
  list_filter = ("operation_type",)
