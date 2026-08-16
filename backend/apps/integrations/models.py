from django.db import models


class AuditLog(models.Model):
  class ActionType(models.TextChoices):
    INTAKE = "intake", "Приёмка"
    ASSEMBLY = "assembly", "Сборка"
    LABEL_PRINT = "label_print", "Печать этикетки"
    MARKING = "marking", "Привязка ЧЗ"
    SUPPLY = "supply", "Поставка"
    RETURN = "return", "Возврат"
    WB_SYNC = "wb_sync", "Синхронизация WB"
    API_ERROR = "api_error", "Ошибка API"
    OTHER = "other", "Прочее"

  user = models.ForeignKey(
    "accounts.User",
    on_delete=models.SET_NULL,
    null=True,
    blank=True,
    related_name="audit_logs",
  )
  seller = models.ForeignKey(
    "sellers.Seller",
    on_delete=models.SET_NULL,
    null=True,
    blank=True,
    related_name="audit_logs",
  )
  action_type = models.CharField(max_length=20, choices=ActionType.choices)
  message = models.TextField()
  details = models.JSONField(default=dict, blank=True)
  created_at = models.DateTimeField(auto_now_add=True)

  class Meta:
    verbose_name = "Журнал действий"
    verbose_name_plural = "Журнал действий"
    ordering = ["-created_at"]
    indexes = [
      models.Index(fields=["action_type", "created_at"]),
      models.Index(fields=["seller", "created_at"]),
    ]
