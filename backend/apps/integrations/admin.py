from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
  list_display = ("action_type", "user", "seller", "created_at")
  list_filter = ("action_type",)
  search_fields = ("message",)
