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
