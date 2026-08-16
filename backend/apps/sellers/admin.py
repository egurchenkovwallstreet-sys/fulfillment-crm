from django.contrib import admin

from .models import Seller


@admin.register(Seller)
class SellerAdmin(admin.ModelAdmin):
  list_display = ("company_name", "is_active", "created_at")
  list_filter = ("is_active",)
  search_fields = ("company_name",)
