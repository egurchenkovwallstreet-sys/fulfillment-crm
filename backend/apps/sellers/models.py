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


class SellerWarehouse(models.Model):
  """Склад продавца в ЛК Wildberries (точка отгрузки FBS)."""

  seller = models.ForeignKey(
    Seller,
    on_delete=models.CASCADE,
    related_name="wb_warehouses",
  )
  wb_warehouse_id = models.BigIntegerField("ID склада WB", db_index=True)
  name = models.CharField("Название", max_length=255, blank=True)
  address = models.CharField("Адрес", max_length=500, blank=True)
  office_id = models.BigIntegerField("ID офиса WB", null=True, blank=True)
  is_enabled = models.BooleanField(
    "Обслуживаем в CRM",
    default=True,
    help_text="Выключенный склад полностью скрыт: заказы не синкаются и не показываются",
  )
  synced_at = models.DateTimeField(null=True, blank=True)
  created_at = models.DateTimeField(auto_now_add=True)
  updated_at = models.DateTimeField(auto_now=True)

  class Meta:
    verbose_name = "Склад WB селлера"
    verbose_name_plural = "Склады WB селлеров"
    unique_together = [("seller", "wb_warehouse_id")]
    ordering = ["name", "wb_warehouse_id"]

  def __str__(self):
    label = self.name or f"Склад #{self.wb_warehouse_id}"
    return f"{self.seller} · {label}"
