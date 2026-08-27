from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

  dependencies = [
    ("warehouse", "0005_cell_marketplace"),
    ("sellers", "0007_seller_ozon_warehouse"),
    ("orders", "0009_supply_wb_warehouse_id"),
  ]

  operations = [
    migrations.CreateModel(
      name="OzonPosting",
      fields=[
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
        ("posting_number", models.CharField(db_index=True, max_length=64, verbose_name="Номер отправления")),
        ("ozon_order_id", models.BigIntegerField(blank=True, null=True, verbose_name="ID заказа Ozon")),
        ("ozon_status", models.CharField(db_index=True, max_length=40, verbose_name="Статус Ozon")),
        (
          "crm_stage",
          models.CharField(
            choices=[
              ("new", "Новые"),
              ("in_picking", "На сборке"),
              ("in_delivery", "В доставке"),
            ],
            db_index=True,
            default="new",
            max_length=20,
            verbose_name="Стадия CRM",
          ),
        ),
        ("ozon_warehouse_id", models.BigIntegerField(blank=True, db_index=True, null=True, verbose_name="ID склада Ozon")),
        ("barcode", models.CharField(blank=True, db_index=True, max_length=100, verbose_name="Баркод")),
        ("offer_id", models.CharField(blank=True, max_length=200, verbose_name="Артикул продавца")),
        ("sku", models.BigIntegerField(blank=True, null=True, verbose_name="SKU Ozon")),
        ("product_name", models.CharField(blank=True, max_length=500, verbose_name="Название")),
        ("quantity", models.PositiveIntegerField(default=1, verbose_name="Количество")),
        ("requires_marking", models.BooleanField(default=False, verbose_name="Требует ЧЗ")),
        ("marking_code", models.CharField(blank=True, max_length=500, verbose_name="Код Честного знака")),
        ("marking_bound", models.BooleanField(default=False, verbose_name="Маркировка привязана")),
        ("stock_deducted", models.BooleanField(default=False, verbose_name="Остаток списан")),
        ("shipment_date", models.DateTimeField(blank=True, null=True)),
        ("in_process_at", models.DateTimeField(blank=True, null=True)),
        ("created_at", models.DateTimeField(auto_now_add=True)),
        ("updated_at", models.DateTimeField(auto_now=True)),
        (
          "product",
          models.ForeignKey(
            blank=True,
            null=True,
            on_delete=django.db.models.deletion.SET_NULL,
            related_name="ozon_postings",
            to="warehouse.product",
          ),
        ),
        (
          "seller",
          models.ForeignKey(
            on_delete=django.db.models.deletion.CASCADE,
            related_name="ozon_postings",
            to="sellers.seller",
          ),
        ),
      ],
      options={
        "verbose_name": "Отправление Ozon",
        "verbose_name_plural": "Отправления Ozon",
        "ordering": ["-in_process_at", "-created_at"],
        "unique_together": {("seller", "posting_number")},
      },
    ),
  ]
