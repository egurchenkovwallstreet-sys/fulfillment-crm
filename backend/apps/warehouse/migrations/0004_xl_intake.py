from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

  dependencies = [
    migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ("sellers", "0001_initial"),
    ("warehouse", "0003_product_catalog_and_warehouse_stocks"),
  ]

  operations = [
    migrations.CreateModel(
      name="XlIntakeSession",
      fields=[
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
        (
          "status",
          models.CharField(
            choices=[
              ("scanning", "Сканирование"),
              ("saved", "Сохранена"),
              ("applied", "Ячейки созданы"),
            ],
            db_index=True,
            default="scanning",
            max_length=20,
          ),
        ),
        (
          "unmatched",
          models.JSONField(blank=True, default=list, verbose_name="Баркоды не найдены в ЛК WB"),
        ),
        ("warehouse_sync_warning", models.CharField(blank=True, max_length=500)),
        ("created_at", models.DateTimeField(auto_now_add=True)),
        ("saved_at", models.DateTimeField(blank=True, null=True)),
        ("applied_at", models.DateTimeField(blank=True, null=True)),
        (
          "created_by",
          models.ForeignKey(
            null=True,
            on_delete=django.db.models.deletion.SET_NULL,
            related_name="xl_intake_sessions",
            to=settings.AUTH_USER_MODEL,
          ),
        ),
        (
          "seller",
          models.ForeignKey(
            on_delete=django.db.models.deletion.CASCADE,
            related_name="xl_intake_sessions",
            to="sellers.seller",
          ),
        ),
      ],
      options={
        "verbose_name": "XL-приёмка",
        "verbose_name_plural": "XL-приёмки",
        "ordering": ["-created_at"],
      },
    ),
    migrations.CreateModel(
      name="XlIntakeLine",
      fields=[
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
        ("barcode", models.CharField(max_length=100, verbose_name="Баркод")),
        ("quantity", models.PositiveIntegerField(default=0, verbose_name="Количество")),
        ("sort_order", models.PositiveIntegerField(verbose_name="Порядковый номер баркода")),
        (
          "session",
          models.ForeignKey(
            on_delete=django.db.models.deletion.CASCADE,
            related_name="lines",
            to="warehouse.xlintakesession",
          ),
        ),
      ],
      options={
        "verbose_name": "Строка XL-приёмки",
        "verbose_name_plural": "Строки XL-приёмки",
        "ordering": ["sort_order"],
        "unique_together": {("session", "barcode")},
      },
    ),
  ]
