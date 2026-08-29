# Generated manually for article intake feature

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

  dependencies = [
    ("warehouse", "0007_xl_intake_resume"),
    migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ("sellers", "0001_initial"),
  ]

  operations = [
    migrations.AddField(
      model_name="product",
      name="article_group_key",
      field=models.CharField(
        blank=True,
        db_index=True,
        max_length=120,
        verbose_name="Ключ группы артикул+цвет",
      ),
    ),
    migrations.AddField(
      model_name="product",
      name="color_label",
      field=models.CharField(
        blank=True,
        max_length=200,
        verbose_name="Цвет (из карточки МП)",
      ),
    ),
    migrations.CreateModel(
      name="ArticleIntakeSession",
      fields=[
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
        (
          "status",
          models.CharField(
            choices=[("active", "Приёмка"), ("completed", "Завершена")],
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
        (
          "confirmed_group_keys",
          models.JSONField(blank=True, default=list, verbose_name="Подтверждённые группы"),
        ),
        ("scan_count", models.PositiveIntegerField(default=0, verbose_name="Сканов")),
        ("total_units", models.PositiveIntegerField(default=0, verbose_name="Принято шт.")),
        ("created_at", models.DateTimeField(auto_now_add=True)),
        ("completed_at", models.DateTimeField(blank=True, null=True)),
        (
          "created_by",
          models.ForeignKey(
            null=True,
            on_delete=models.deletion.SET_NULL,
            related_name="article_intake_sessions",
            to=settings.AUTH_USER_MODEL,
          ),
        ),
        (
          "seller",
          models.ForeignKey(
            on_delete=models.deletion.CASCADE,
            related_name="article_intake_sessions",
            to="sellers.seller",
            verbose_name="Селлер",
          ),
        ),
      ],
      options={
        "verbose_name": "Приёмка по артикулам",
        "verbose_name_plural": "Приёмки по артикулам",
        "ordering": ["-created_at"],
      },
    ),
  ]
