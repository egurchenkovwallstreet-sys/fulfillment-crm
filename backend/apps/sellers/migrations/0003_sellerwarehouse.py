# Generated manually

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

  dependencies = [
    ("sellers", "0002_seller_wb_counts"),
  ]

  operations = [
    migrations.CreateModel(
      name="SellerWarehouse",
      fields=[
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
        ("wb_warehouse_id", models.BigIntegerField(db_index=True, verbose_name="ID склада WB")),
        ("name", models.CharField(blank=True, max_length=255, verbose_name="Название")),
        ("address", models.CharField(blank=True, max_length=500, verbose_name="Адрес")),
        ("office_id", models.BigIntegerField(blank=True, null=True, verbose_name="ID офиса WB")),
        (
          "is_enabled",
          models.BooleanField(
            default=True,
            help_text="Выключенный склад полностью скрыт: заказы не синкаются и не показываются",
            verbose_name="Обслуживаем в CRM",
          ),
        ),
        ("synced_at", models.DateTimeField(blank=True, null=True)),
        ("created_at", models.DateTimeField(auto_now_add=True)),
        ("updated_at", models.DateTimeField(auto_now=True)),
        (
          "seller",
          models.ForeignKey(
            on_delete=django.db.models.deletion.CASCADE,
            related_name="wb_warehouses",
            to="sellers.seller",
          ),
        ),
      ],
      options={
        "verbose_name": "Склад WB селлера",
        "verbose_name_plural": "Склады WB селлеров",
        "ordering": ["name", "wb_warehouse_id"],
        "unique_together": {("seller", "wb_warehouse_id")},
      },
    ),
  ]
