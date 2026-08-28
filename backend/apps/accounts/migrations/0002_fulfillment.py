# Generated manually for multi-tenant Fulfillment model

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def create_default_fulfillment(apps, schema_editor):
  Fulfillment = apps.get_model("accounts", "Fulfillment")
  User = apps.get_model("accounts", "User")
  fulfillment, _ = Fulfillment.objects.get_or_create(
    slug="default",
    defaults={"name": "Основной фулфилмент"},
  )
  User.objects.filter(role__in=("admin", "manager")).update(fulfillment=fulfillment)


class Migration(migrations.Migration):

  dependencies = [
    ("accounts", "0001_initial"),
  ]

  operations = [
    migrations.CreateModel(
      name="Fulfillment",
      fields=[
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
        ("name", models.CharField(max_length=255, verbose_name="Название")),
        ("slug", models.SlugField(max_length=100, unique=True, verbose_name="Код")),
        ("is_active", models.BooleanField(default=True, verbose_name="Активен")),
        ("created_at", models.DateTimeField(auto_now_add=True)),
        ("updated_at", models.DateTimeField(auto_now=True)),
      ],
      options={
        "verbose_name": "Фулфилмент",
        "verbose_name_plural": "Фулфилменты",
        "ordering": ["name"],
      },
    ),
    migrations.AddField(
      model_name="user",
      name="fulfillment",
      field=models.ForeignKey(
        blank=True,
        null=True,
        on_delete=django.db.models.deletion.CASCADE,
        related_name="users",
        to="accounts.fulfillment",
        verbose_name="Фулфилмент",
      ),
    ),
    migrations.RunPython(create_default_fulfillment, migrations.RunPython.noop),
  ]
