from django.db import models


class Order(models.Model):
  class Status(models.TextChoices):
    NEW = "new", "Новый"
    IN_PICKING = "in_picking", "В подборе"
    ASSEMBLED = "assembled", "Собран"
    LABEL_PRINTED = "label_printed", "Этикетка напечатана"
    MARKED = "marked", "Маркировка привязана"
    IN_SUPPLY = "in_supply", "В поставке"
    IN_DELIVERY = "in_delivery", "В доставке"
    SHIPPED = "shipped", "Отправлен"
    CANCELLED = "cancelled", "Отменён"

  seller = models.ForeignKey(
    "sellers.Seller",
    on_delete=models.CASCADE,
    related_name="orders",
  )
  wb_order_id = models.BigIntegerField("ID заказа WB", unique=True)
  barcode = models.CharField("Баркод заказа", max_length=100)
  wb_warehouse_id = models.BigIntegerField("ID склада WB", null=True, blank=True, db_index=True)
  product = models.ForeignKey(
    "warehouse.Product",
    on_delete=models.PROTECT,
    related_name="orders",
    null=True,
    blank=True,
  )
  status = models.CharField(
    max_length=20,
    choices=Status.choices,
    default=Status.NEW,
  )
  wb_supplier_status = models.CharField(
    "Статус WB (supplier)",
    max_length=30,
    blank=True,
    db_index=True,
  )
  wb_status = models.CharField(
    "Статус WB (wb)",
    max_length=30,
    blank=True,
  )
  pick_list = models.ForeignKey(
    "PickList",
    on_delete=models.SET_NULL,
    null=True,
    blank=True,
    related_name="orders",
  )
  has_sticker = models.BooleanField("Стикер получен", default=False)
  sticker_file = models.TextField("Стикер (base64)", blank=True)
  sticker_part_a = models.CharField("Стикер partA", max_length=50, blank=True)
  sticker_part_b = models.CharField("Стикер partB", max_length=50, blank=True)
  sticker_fetched_at = models.DateTimeField(null=True, blank=True)
  marking_code = models.CharField("Код Честного знака", max_length=500, blank=True)
  marking_bound = models.BooleanField("Маркировка привязана", default=False)
  created_at = models.DateTimeField(auto_now_add=True)
  updated_at = models.DateTimeField(auto_now=True)

  class Meta:
    verbose_name = "Заказ"
    verbose_name_plural = "Заказы"
    ordering = ["-created_at"]
    indexes = [
      models.Index(fields=["wb_order_id"]),
      models.Index(fields=["seller", "status"]),
      models.Index(fields=["seller", "wb_supplier_status"]),
      models.Index(fields=["barcode"]),
    ]

  def __str__(self):
    return f"WB #{self.wb_order_id}"


class PickList(models.Model):
  seller = models.ForeignKey(
    "sellers.Seller",
    on_delete=models.CASCADE,
    related_name="pick_lists",
  )
  created_at = models.DateTimeField(auto_now_add=True)
  is_completed = models.BooleanField(default=False)

  class Meta:
    verbose_name = "Лист подбора"
    verbose_name_plural = "Листы подбора"
    ordering = ["-created_at"]


class PickListItem(models.Model):
  pick_list = models.ForeignKey(
    PickList,
    on_delete=models.CASCADE,
    related_name="items",
  )
  cell = models.ForeignKey("warehouse.Cell", on_delete=models.PROTECT)
  product = models.ForeignKey("warehouse.Product", on_delete=models.PROTECT)
  barcode = models.CharField(max_length=100)
  quantity = models.PositiveIntegerField("Количество собрать")
  picked_quantity = models.PositiveIntegerField("Собрано", default=0)

  class Meta:
    verbose_name = "Позиция листа подбора"
    verbose_name_plural = "Позиции листа подбора"


class Supply(models.Model):
  class Status(models.TextChoices):
    FORMING = "forming", "Формируется"
    READY = "ready", "Готова"
    CONFIRMED = "confirmed", "Подтверждена WB"
    SHIPPED = "shipped", "Отправлена"

  seller = models.ForeignKey(
    "sellers.Seller",
    on_delete=models.CASCADE,
    related_name="supplies",
  )
  wb_supply_id = models.CharField("ID поставки WB", max_length=100, blank=True)
  status = models.CharField(
    max_length=20,
    choices=Status.choices,
    default=Status.FORMING,
  )
  orders = models.ManyToManyField(Order, related_name="supplies", blank=True)
  supply_barcode_printed = models.BooleanField("ШК поставки распечатан", default=False)
  stock_deducted = models.BooleanField("Остатки списаны", default=False)
  created_at = models.DateTimeField(auto_now_add=True)
  updated_at = models.DateTimeField(auto_now=True)

  class Meta:
    verbose_name = "Поставка"
    verbose_name_plural = "Поставки"
    ordering = ["-created_at"]
