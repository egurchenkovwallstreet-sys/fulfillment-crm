from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

  dependencies = [
    ("warehouse", "0011_product_dimensions"),
    ("sellers", "0003_sellerwarehouse"),
    migrations.swappable_dependency(settings.AUTH_USER_MODEL),
  ]

  operations = [
    migrations.CreateModel(
      name="WbFactIntakeSession",
      fields=[
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
        (
          "status",
          models.CharField(
            choices=[("scanning", "Приёмка"), ("completed", "Завершена")],
            db_index=True,
            default="scanning",
            max_length=20,
          ),
        ),
        (
          "marketplace",
          models.CharField(
            choices=[("wb", "Wildberries"), ("ozon", "Ozon")],
            db_index=True,
            default="wb",
            max_length=8,
            verbose_name="Маркетплейс",
          ),
        ),
        ("catalog_count", models.PositiveIntegerField(default=0, verbose_name="Карточек в каталоге")),
        ("accepted_count", models.PositiveIntegerField(default=0, verbose_name="Принято баркодов")),
        ("created_at", models.DateTimeField(auto_now_add=True)),
        ("completed_at", models.DateTimeField(blank=True, null=True)),
        ("wb_pushed_at", models.DateTimeField(blank=True, null=True, verbose_name="Выгрузка в ЛК WB")),
        (
          "created_by",
          models.ForeignKey(
            null=True,
            on_delete=django.db.models.deletion.SET_NULL,
            related_name="wb_fact_intake_sessions",
            to=settings.AUTH_USER_MODEL,
          ),
        ),
        (
          "seller",
          models.ForeignKey(
            on_delete=django.db.models.deletion.CASCADE,
            related_name="wb_fact_intake_sessions",
            to="sellers.seller",
          ),
        ),
        (
          "warehouse",
          models.ForeignKey(
            on_delete=django.db.models.deletion.PROTECT,
            related_name="wb_fact_intake_sessions",
            to="sellers.sellerwarehouse",
            verbose_name="Склад FBS WB",
          ),
        ),
      ],
      options={
        "verbose_name": "Приёмка карточек WB",
        "verbose_name_plural": "Приёмки карточек WB",
        "ordering": ["-created_at"],
      },
    ),
    migrations.CreateModel(
      name="WbFactIntakeLine",
      fields=[
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
        ("barcode", models.CharField(max_length=100, verbose_name="Баркод")),
        ("wb_nm_id", models.BigIntegerField(blank=True, null=True, verbose_name="Артикул WB (nmID)")),
        ("vendor_code", models.CharField(blank=True, max_length=200, verbose_name="Артикул продавца")),
        ("title", models.CharField(blank=True, max_length=500, verbose_name="Название")),
        ("tech_size", models.CharField(blank=True, max_length=50, verbose_name="Размер (EU/тех.)")),
        ("wb_size", models.CharField(blank=True, max_length=50, verbose_name="Размер (RU)")),
        ("photo_url", models.URLField(blank=True, max_length=500, verbose_name="Фото WB")),
        ("color_label", models.CharField(blank=True, max_length=200, verbose_name="Цвет")),
        ("requires_marking", models.BooleanField(default=False, verbose_name="Требует ЧЗ")),
        ("wb_stock_snapshot", models.PositiveIntegerField(default=0, verbose_name="Остаток WB на старте")),
        ("accepted", models.BooleanField(db_index=True, default=False, verbose_name="Отсканирован")),
        ("fact_quantity", models.PositiveIntegerField(default=0, verbose_name="Факт CRM")),
        ("cell_number", models.CharField(blank=True, default="", max_length=50, verbose_name="Ячейка")),
        ("scanned_at", models.DateTimeField(blank=True, null=True)),
        (
          "product",
          models.ForeignKey(
            blank=True,
            null=True,
            on_delete=django.db.models.deletion.SET_NULL,
            related_name="wb_fact_intake_lines",
            to="warehouse.product",
          ),
        ),
        (
          "session",
          models.ForeignKey(
            on_delete=django.db.models.deletion.CASCADE,
            related_name="lines",
            to="warehouse.wbfactintakesession",
          ),
        ),
      ],
      options={
        "verbose_name": "Строка приёмки карточек WB",
        "verbose_name_plural": "Строки приёмки карточек WB",
        "unique_together": {("session", "barcode")},
      },
    ),
    migrations.AddIndex(
      model_name="wbfactintakeline",
      index=models.Index(fields=["session", "accepted"], name="wh_fact_sess_acc_idx"),
    ),
  ]
