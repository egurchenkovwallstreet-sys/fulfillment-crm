from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

  dependencies = [
    migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ("sellers", "0015_sellerwarehouse_cargo_type"),
    ("warehouse", "0017_product_barcode_alias"),
  ]

  operations = [
    migrations.CreateModel(
      name="FboAssemblySession",
      fields=[
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
        (
          "status",
          models.CharField(
            choices=[("active", "В работе"), ("paused", "Пауза"), ("completed", "Завершена")],
            db_index=True,
            default="active",
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
        ("created_at", models.DateTimeField(auto_now_add=True)),
        ("completed_at", models.DateTimeField(blank=True, null=True)),
        (
          "created_by",
          models.ForeignKey(
            null=True,
            on_delete=django.db.models.deletion.SET_NULL,
            related_name="fbo_assembly_sessions",
            to=settings.AUTH_USER_MODEL,
          ),
        ),
        (
          "seller",
          models.ForeignKey(
            on_delete=django.db.models.deletion.CASCADE,
            related_name="fbo_assembly_sessions",
            to="sellers.seller",
          ),
        ),
      ],
      options={
        "verbose_name": "Сборка FBO",
        "verbose_name_plural": "Сборки FBO",
        "ordering": ["-created_at"],
      },
    ),
    migrations.CreateModel(
      name="FboAssemblyBox",
      fields=[
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
        ("box_number", models.CharField(max_length=100, verbose_name="Номер короба")),
        (
          "status",
          models.CharField(
            choices=[("open", "Открыт"), ("closed", "Закрыт")],
            db_index=True,
            default="open",
            max_length=20,
          ),
        ),
        ("sort_order", models.PositiveIntegerField(default=1, verbose_name="Порядок короба")),
        ("created_at", models.DateTimeField(auto_now_add=True)),
        ("closed_at", models.DateTimeField(blank=True, null=True)),
        (
          "session",
          models.ForeignKey(
            on_delete=django.db.models.deletion.CASCADE,
            related_name="boxes",
            to="warehouse.fboassemblysession",
          ),
        ),
      ],
      options={
        "verbose_name": "Короб FBO",
        "verbose_name_plural": "Короба FBO",
        "ordering": ["sort_order", "id"],
      },
    ),
    migrations.CreateModel(
      name="FboAssemblyLine",
      fields=[
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
        ("barcode", models.CharField(max_length=100, verbose_name="Баркод")),
        ("quantity", models.PositiveIntegerField(default=0, verbose_name="Количество")),
        (
          "box",
          models.ForeignKey(
            on_delete=django.db.models.deletion.CASCADE,
            related_name="lines",
            to="warehouse.fboassemblybox",
          ),
        ),
        (
          "product",
          models.ForeignKey(
            blank=True,
            null=True,
            on_delete=django.db.models.deletion.SET_NULL,
            related_name="fbo_assembly_lines",
            to="warehouse.product",
          ),
        ),
      ],
      options={
        "verbose_name": "Строка короба FBO",
        "verbose_name_plural": "Строки коробов FBO",
        "ordering": ["id"],
        "unique_together": {("box", "barcode")},
      },
    ),
  ]
