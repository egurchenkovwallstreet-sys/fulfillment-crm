from django.contrib import admin

from .models import Fulfillment, User


@admin.register(Fulfillment)
class FulfillmentAdmin(admin.ModelAdmin):
  list_display = ("name", "slug", "is_active", "created_at")
  search_fields = ("name", "slug")
  prepopulated_fields = {"slug": ("name",)}


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
  list_display = ("username", "email", "role", "fulfillment", "is_active")
  list_filter = ("role", "is_active", "fulfillment")
  search_fields = ("username", "email")
