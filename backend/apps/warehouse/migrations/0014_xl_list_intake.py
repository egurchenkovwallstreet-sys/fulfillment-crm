from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

  dependencies = [
    ("accounts", "0001_initial"),
    ("warehouse", "0013_product_daily_quantity"),
    migrations.swappable_dependency(settings.AUTH_USER_MODEL),
  ]

  operations = [
    migrations.CreateModel(
      name="XlListSession",
      fields=[
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
        ("title", models.CharField(blank=True, default="", max_length=200, verbose_name="Название")),
        (
          "status",
          models.CharField(
            choices=[("active", "Сбор списка"), ("completed", "Завершена")],
            db_index=True,
            default="active",
            max_length=20,
          ),
        ),
        ("created_at", models.DateTimeField(auto_now_add=True)),
        ("completed_at", models.DateTimeField(blank=True, null=True)),
        (
          "created_by",
          models.ForeignKey(
            null=True,
            on_delete=django.db.models.deletion.SET_NULL,
            related_name="xl_list_sessions",
            to=settings.AUTH_USER_MODEL,
          ),
        ),
        (
          "fulfillment",
          models.ForeignKey(
            on_delete=django.db.models.deletion.CASCADE,
            related_name="xl_list_sessions",
            to="accounts.fulfillment",
          ),
        ),
      ],
      options={
        "verbose_name": "XL-список (Excel)",
        "verbose_name_plural": "XL-списки (Excel)",
        "ordering": ["-created_at"],
      },
    ),
    migrations.CreateModel(
      name="XlListLine",
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
            to="warehouse.xllistsession",
          ),
        ),
      ],
      options={
        "verbose_name": "Строка XL-списка",
        "verbose_name_plural": "Строки XL-списка",
        "ordering": ["sort_order"],
        "unique_together": {("session", "barcode")},
      },
    ),
  ]
