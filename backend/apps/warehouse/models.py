from decimal import Decimal

from django.db import models


class PriceGroup(models.Model):
  name = models.CharField("Название группы", max_length=100)
  processing_price = models.DecimalField(
    "Стоимость обработки за единицу",
    max_digits=10,
    decimal_places=2,
    default=Decimal("0.00"),
  )
  sort_order = models.PositiveSmallIntegerField("Порядок", default=0)

  class Meta:
    verbose_name = "Ценовая группа"
    verbose_name_plural = "Ценовые группы"
    ordering = ["sort_order", "name"]

  def __str__(self):
    return self.name


class Cell(models.Model):
  seller = models.ForeignKey(
    "sellers.Seller",
    on_delete=models.CASCADE,
    related_name="cells",
    verbose_name="Селлер",
  )
  number = models.CharField("Номер ячейки", max_length=50)
  is_occupied = models.BooleanField("Занята", default=False)
  created_at = models.DateTimeField(auto_now_add=True)

  class Meta:
    verbose_name = "Ячейка"
    verbose_name_plural = "Ячейки"
    ordering = ["number"]
    unique_together = [("seller", "number")]

  def __str__(self):
    return f"{self.seller_id}: №{self.number}"


class Product(models.Model):
  seller = models.ForeignKey(
    "sellers.Seller",
    on_delete=models.CASCADE,
    related_name="products",
    verbose_name="Селлер",
  )
  barcode = models.CharField("Баркод", max_length=100)
  name = models.CharField("Название", max_length=500, blank=True)
  cell = models.ForeignKey(
    Cell,
    on_delete=models.PROTECT,
    related_name="products",
    verbose_name="Ячейка",
  )
  price_group = models.ForeignKey(
    PriceGroup,
    on_delete=models.SET_NULL,
    null=True,
    blank=True,
    related_name="products",
    verbose_name="Ценовая группа",
  )
  individual_price = models.DecimalField(
    "Индивидуальная стоимость",
    max_digits=10,
    decimal_places=2,
    null=True,
    blank=True,
  )
  requires_marking = models.BooleanField("Требует маркировку (ЧЗ)", default=False)
  wb_nm_id = models.BigIntegerField("Артикул WB (nmID)", null=True, blank=True, db_index=True)
  vendor_code = models.CharField("Артикул продавца", max_length=200, blank=True)
  tech_size = models.CharField("Размер (EU/тех.)", max_length=50, blank=True)
  wb_size = models.CharField("Размер (RU)", max_length=50, blank=True)
  photo_url = models.URLField("Фото WB", max_length=500, blank=True)
  quantity = models.PositiveIntegerField("Остаток", default=0)
  created_at = models.DateTimeField(auto_now_add=True)
  updated_at = models.DateTimeField(auto_now=True)

  class Meta:
    verbose_name = "Товар"
    verbose_name_plural = "Товары"
    unique_together = [("seller", "barcode")]
    indexes = [
      models.Index(fields=["barcode"]),
      models.Index(fields=["seller", "barcode"]),
    ]

  def __str__(self):
    return f"{self.barcode} ({self.seller})"

  @property
  def processing_price(self):
    if self.individual_price is not None:
      return self.individual_price
    if self.price_group:
      return self.price_group.processing_price
    return None


class ProductWarehouseStock(models.Model):
  """Остаток баркода на конкретном FBS-складе WB (для перераспределения)."""
  product = models.ForeignKey(
    Product,
    on_delete=models.CASCADE,
    related_name="warehouse_stocks",
  )
  seller_warehouse = models.ForeignKey(
    "sellers.SellerWarehouse",
    on_delete=models.CASCADE,
    related_name="product_stocks",
  )
  quantity = models.PositiveIntegerField("Остаток на складе WB", default=0)
  updated_at = models.DateTimeField(auto_now=True)

  class Meta:
    verbose_name = "Остаток на складе WB"
    verbose_name_plural = "Остатки на складах WB"
    unique_together = [("product", "seller_warehouse")]

  def __str__(self):
    return f"{self.product.barcode} @ {self.seller_warehouse_id}: {self.quantity}"


class StockOperation(models.Model):
  class OperationType(models.TextChoices):
    INTAKE = "intake", "Приёмка"
    SHIPMENT = "shipment", "Списание (поставка)"
    RETURN = "return", "Возврат"
    ADJUSTMENT = "adjustment", "Корректировка"

  product = models.ForeignKey(
    Product,
    on_delete=models.CASCADE,
    related_name="stock_operations",
  )
  operation_type = models.CharField(max_length=20, choices=OperationType.choices)
  quantity = models.IntegerField("Количество")
  performed_by = models.ForeignKey(
    "accounts.User",
    on_delete=models.SET_NULL,
    null=True,
    related_name="stock_operations",
  )
  comment = models.TextField(blank=True)
  created_at = models.DateTimeField(auto_now_add=True)

  class Meta:
    verbose_name = "Складская операция"
    verbose_name_plural = "Складские операции"
    ordering = ["-created_at"]


class XlIntakeSession(models.Model):
  class Status(models.TextChoices):
    SCANNING = "scanning", "Сканирование"
    SAVED = "saved", "Сохранена"
    APPLIED = "applied", "Ячейки созданы"

  seller = models.ForeignKey(
    "sellers.Seller",
    on_delete=models.CASCADE,
    related_name="xl_intake_sessions",
  )
  status = models.CharField(
    max_length=20,
    choices=Status.choices,
    default=Status.SCANNING,
    db_index=True,
  )
  created_by = models.ForeignKey(
    "accounts.User",
    on_delete=models.SET_NULL,
    null=True,
    related_name="xl_intake_sessions",
  )
  unmatched = models.JSONField("Баркоды не найдены в ЛК WB", default=list, blank=True)
  warehouse_sync_warning = models.CharField(max_length=500, blank=True)
  created_at = models.DateTimeField(auto_now_add=True)
  saved_at = models.DateTimeField(null=True, blank=True)
  applied_at = models.DateTimeField(null=True, blank=True)

  class Meta:
    verbose_name = "XL-приёмка"
    verbose_name_plural = "XL-приёмки"
    ordering = ["-created_at"]

  def __str__(self):
    return f"XL #{self.pk} · {self.seller}"


class XlIntakeLine(models.Model):
  session = models.ForeignKey(
    XlIntakeSession,
    on_delete=models.CASCADE,
    related_name="lines",
  )
  barcode = models.CharField("Баркод", max_length=100)
  quantity = models.PositiveIntegerField("Количество", default=0)
  sort_order = models.PositiveIntegerField("Порядковый номер баркода")

  class Meta:
    verbose_name = "Строка XL-приёмки"
    verbose_name_plural = "Строки XL-приёмки"
    unique_together = [("session", "barcode")]
    ordering = ["sort_order"]

  def __str__(self):
    return f"{self.barcode} × {self.quantity}"
