import uuid

from django.db import models


class Seller(models.Model):
  fulfillment = models.ForeignKey(
    "accounts.Fulfillment",
    on_delete=models.CASCADE,
    related_name="sellers",
    verbose_name="Фулфилмент",
  )
  company_name = models.CharField("ИП / название компании", max_length=255)
  wb_api_token_encrypted = models.TextField("WB API токен (зашифрован)", blank=True)
  is_active = models.BooleanField("Активен", default=True)
  wb_enabled = models.BooleanField("Wildberries", default=True)
  ozon_enabled = models.BooleanField("Ozon", default=False)
  ozon_client_id = models.CharField("Ozon Client-Id", max_length=64, blank=True)
  ozon_api_key_encrypted = models.TextField("Ozon Api-Key (зашифрован)", blank=True)
  wb_count_new = models.PositiveIntegerField("WB: новые", default=0)
  wb_count_assembly = models.PositiveIntegerField("WB: на сборке", default=0)
  wb_count_delivery = models.PositiveIntegerField("WB: в доставке", default=0)
  wb_counts_synced_at = models.DateTimeField("WB: счётчики обновлены", null=True, blank=True)
  wb_new_order_ids = models.JSONField(
    "WB: ID новых заказов (последний sync)",
    default=list,
    blank=True,
  )
  ozon_count_new = models.PositiveIntegerField("Ozon: новые", default=0)
  ozon_count_assembly = models.PositiveIntegerField("Ozon: на сборке", default=0)
  ozon_count_delivery = models.PositiveIntegerField("Ozon: в доставке", default=0)
  ozon_counts_synced_at = models.DateTimeField("Ozon: счётчики обновлены", null=True, blank=True)
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


class SellerOzonWarehouse(models.Model):
  """Склад продавца в ЛК Ozon (точка отгрузки FBS)."""

  seller = models.ForeignKey(
    Seller,
    on_delete=models.CASCADE,
    related_name="ozon_warehouses",
  )
  ozon_warehouse_id = models.BigIntegerField("ID склада Ozon", db_index=True)
  name = models.CharField("Название", max_length=255, blank=True)
  is_rfbs = models.BooleanField("rFBS", default=False)
  is_enabled = models.BooleanField(
    "Обслуживаем в CRM",
    default=True,
    help_text="Выключенный склад скрыт: отправления не синкаются и не показываются",
  )
  synced_at = models.DateTimeField(null=True, blank=True)
  created_at = models.DateTimeField(auto_now_add=True)
  updated_at = models.DateTimeField(auto_now=True)

  class Meta:
    verbose_name = "Склад Ozon селлера"
    verbose_name_plural = "Склады Ozon селлеров"
    unique_together = [("seller", "ozon_warehouse_id")]
    ordering = ["name", "ozon_warehouse_id"]

  def __str__(self):
    label = self.name or f"Склад #{self.ozon_warehouse_id}"
    return f"{self.seller} · {label}"


class SellerInvite(models.Model):
  """Одноразовая ссылка для регистрации селлера в CRM."""

  seller = models.OneToOneField(
    Seller,
    on_delete=models.CASCADE,
    related_name="invite",
  )
  token = models.UUIDField("Токен", default=uuid.uuid4, unique=True, editable=False)
  is_active = models.BooleanField("Активна", default=True)
  used_at = models.DateTimeField("Использована", null=True, blank=True)
  created_at = models.DateTimeField(auto_now_add=True)
  updated_at = models.DateTimeField(auto_now=True)

  class Meta:
    verbose_name = "Приглашение селлера"
    verbose_name_plural = "Приглашения селлеров"

  def __str__(self):
    return f"Invite {self.seller.company_name}"
