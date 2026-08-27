from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

  dependencies = [
    ("sellers", "0006_seller_marketplace"),
  ]

  operations = [
    migrations.CreateModel(
      name="SellerOzonWarehouse",
      fields=[
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
        ("ozon_warehouse_id", models.BigIntegerField(db_index=True, verbose_name="ID склада Ozon")),
        ("name", models.CharField(blank=True, max_length=255, verbose_name="Название")),
        ("is_rfbs", models.BooleanField(default=False, verbose_name="rFBS")),
        (
          "is_enabled",
          models.BooleanField(
            default=True,
            help_text="Выключенный склад скрыт: отправления не синкаются и не показываются",
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
            related_name="ozon_warehouses",
            to="sellers.seller",
          ),
        ),
      ],
      options={
        "verbose_name": "Склад Ozon селлера",
        "verbose_name_plural": "Склады Ozon селлеров",
        "ordering": ["name", "ozon_warehouse_id"],
        "unique_together": {("seller", "ozon_warehouse_id")},
      },
    ),
  ]
