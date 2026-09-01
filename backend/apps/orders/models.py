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
  wb_order_id = models.BigIntegerField("ID заказа WB")
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
  marking_verify_status = models.CharField(
    "Статус проверки ЧЗ в WB",
    max_length=20,
    blank=True,
    db_index=True,
  )
  marking_verify_error = models.TextField("Ошибка проверки ЧЗ", blank=True)
  in_delivery_at = models.DateTimeField(
    "Передан в доставку",
    null=True,
    blank=True,
    db_index=True,
  )
  wb_created_at = models.DateTimeField("Дата заказа WB", null=True, blank=True, db_index=True)
  assembly_hidden = models.BooleanField(
    "Скрыт из сборки FBS",
    default=False,
    db_index=True,
  )
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
    constraints = [
      models.UniqueConstraint(fields=["seller", "wb_order_id"], name="uniq_order_seller_wb_id"),
    ]

  def __str__(self):
    return f"WB #{self.wb_order_id}"


class PickList(models.Model):
  seller = models.ForeignKey(
    "sellers.Seller",
    on_delete=models.CASCADE,
    related_name="pick_lists",
  )
  marketplace = models.CharField(
    "Маркетплейс",
    max_length=10,
    choices=(("wb", "Wildberries"), ("ozon", "Ozon")),
    default="wb",
    db_index=True,
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
  cell = models.ForeignKey("warehouse.Cell", on_delete=models.PROTECT, null=True, blank=True)
  product = models.ForeignKey("warehouse.Product", on_delete=models.PROTECT, null=True, blank=True)
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
  wb_warehouse_id = models.BigIntegerField(
    "ID склада WB",
    null=True,
    blank=True,
    db_index=True,
  )
  status = models.CharField(
    max_length=20,
    choices=Status.choices,
    default=Status.FORMING,
  )
  orders = models.ManyToManyField(Order, related_name="supplies", blank=True)
  supply_barcode_printed = models.BooleanField("ШК поставки распечатан", default=False)
  wb_scanned_at = models.DateTimeField("ШК поставки отсканирован на складе WB", null=True, blank=True)
  stock_deducted = models.BooleanField("Остатки списаны", default=False)
  created_at = models.DateTimeField(auto_now_add=True)
  updated_at = models.DateTimeField(auto_now=True)

  class Meta:
    verbose_name = "Поставка"
    verbose_name_plural = "Поставки"
    ordering = ["-created_at"]


class OzonPosting(models.Model):
  class CrmStage(models.TextChoices):
    NEW = "new", "Новые"
    IN_PICKING = "in_picking", "На сборке"
    IN_DELIVERY = "in_delivery", "В доставке"

  seller = models.ForeignKey(
    "sellers.Seller",
    on_delete=models.CASCADE,
    related_name="ozon_postings",
  )
  posting_number = models.CharField("Номер отправления", max_length=64, db_index=True)
  ozon_order_id = models.BigIntegerField("ID заказа Ozon", null=True, blank=True)
  ozon_status = models.CharField("Статус Ozon", max_length=40, db_index=True)
  crm_stage = models.CharField(
    "Стадия CRM",
    max_length=20,
    choices=CrmStage.choices,
    default=CrmStage.NEW,
    db_index=True,
  )
  ozon_warehouse_id = models.BigIntegerField("ID склада Ozon", null=True, blank=True, db_index=True)
  barcode = models.CharField("Баркод", max_length=100, blank=True, db_index=True)
  offer_id = models.CharField("Артикул продавца", max_length=200, blank=True)
  sku = models.BigIntegerField("SKU Ozon", null=True, blank=True)
  product_name = models.CharField("Название", max_length=500, blank=True)
  quantity = models.PositiveIntegerField("Количество", default=1)
  requires_marking = models.BooleanField("Требует ЧЗ", default=False)
  product = models.ForeignKey(
    "warehouse.Product",
    on_delete=models.SET_NULL,
    null=True,
    blank=True,
    related_name="ozon_postings",
  )
  marking_code = models.CharField("Код Честного знака", max_length=500, blank=True)
  marking_codes = models.JSONField("Коды Честного знака", default=list, blank=True)
  marking_bound = models.BooleanField("Маркировка привязана", default=False)
  stock_deducted = models.BooleanField("Остаток списан", default=False)
  shipped_at = models.DateTimeField("Передано к отгрузке", null=True, blank=True, db_index=True)
  delivery_method_id = models.BigIntegerField("ID метода доставки Ozon", null=True, blank=True, db_index=True)
  carriage_id = models.BigIntegerField("ID отгрузки Ozon", null=True, blank=True, db_index=True)
  pick_list = models.ForeignKey(
    "PickList",
    on_delete=models.SET_NULL,
    null=True,
    blank=True,
    related_name="ozon_postings",
  )
  products_json = models.JSONField("Товары отправления", default=list, blank=True)
  shipment_date = models.DateTimeField(null=True, blank=True)
  in_process_at = models.DateTimeField(null=True, blank=True)
  created_at = models.DateTimeField(auto_now_add=True)
  updated_at = models.DateTimeField(auto_now=True)

  class Meta:
    verbose_name = "Отправление Ozon"
    verbose_name_plural = "Отправления Ozon"
    unique_together = [("seller", "posting_number")]
    ordering = ["-in_process_at", "-created_at"]

  def __str__(self):
    return self.posting_number


class OffCrmShipment(models.Model):
  class Status(models.TextChoices):
    PENDING = "pending", "Ожидает решения"
    DEDUCTED = "deducted", "Списано"
    SKIPPED = "skipped", "Не списывать"

  seller = models.ForeignKey(
    "sellers.Seller",
    on_delete=models.CASCADE,
    related_name="off_crm_shipments",
  )
  crm_order = models.ForeignKey(
    Order,
    on_delete=models.SET_NULL,
    null=True,
    blank=True,
    related_name="off_crm_shipments",
  )
  wb_order_id = models.BigIntegerField("ID заказа WB", db_index=True)
  barcode = models.CharField("Баркод", max_length=100, db_index=True)
  sticker_part_a = models.CharField("Стикер partA", max_length=50)
  sticker_part_b = models.CharField("Стикер partB", max_length=50)
  sticker_number = models.CharField("Номер стикера", max_length=120, blank=True)
  wb_supply_id = models.CharField("ID поставки WB", max_length=100, blank=True, db_index=True)
  wb_warehouse_id = models.BigIntegerField("ID склада WB", null=True, blank=True, db_index=True)
  warehouse_name = models.CharField("Склад", max_length=200, blank=True)
  quantity = models.PositiveIntegerField("Количество", default=1)
  shipped_at = models.DateTimeField("Отгружено в WB", null=True, blank=True, db_index=True)
  detected_at = models.DateTimeField("Обнаружено", auto_now_add=True)
  status = models.CharField(
    max_length=20,
    choices=Status.choices,
    default=Status.PENDING,
    db_index=True,
  )
  resolved_by = models.ForeignKey(
    "accounts.User",
    on_delete=models.SET_NULL,
    null=True,
    blank=True,
    related_name="resolved_off_crm_shipments",
  )
  resolved_at = models.DateTimeField(null=True, blank=True)

  class Meta:
    verbose_name = "Отгрузка вне CRM"
    verbose_name_plural = "Отгрузки вне CRM"
    ordering = ["-shipped_at", "-detected_at"]
    constraints = [
      models.UniqueConstraint(
        fields=["seller", "sticker_part_a", "sticker_part_b"],
        name="uniq_off_crm_sticker_per_seller",
      ),
    ]
    indexes = [
      models.Index(fields=["seller", "status"]),
    ]

  def __str__(self):
    return f"WB #{self.wb_order_id} ({self.get_status_display()})"
