from django.db import models


class Seller(models.Model):
  company_name = models.CharField("ИП / название компании", max_length=255)
  wb_api_token_encrypted = models.TextField("WB API токен (зашифрован)", blank=True)
  is_active = models.BooleanField("Активен", default=True)
  wb_count_new = models.PositiveIntegerField("WB: новые", default=0)
  wb_count_assembly = models.PositiveIntegerField("WB: на сборке", default=0)
  wb_count_delivery = models.PositiveIntegerField("WB: в доставке", default=0)
  wb_counts_synced_at = models.DateTimeField("WB: счётчики обновлены", null=True, blank=True)
  created_at = models.DateTimeField(auto_now_add=True)
  updated_at = models.DateTimeField(auto_now=True)

  class Meta:
    verbose_name = "Селлер"
    verbose_name_plural = "Селлеры"
    ordering = ["company_name"]

  def __str__(self):
    return self.company_name
