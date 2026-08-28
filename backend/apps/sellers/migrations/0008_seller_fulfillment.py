# Generated manually — attach sellers to default fulfillment

import django.db.models.deletion
from django.db import migrations, models


def backfill_seller_fulfillment(apps, schema_editor):
  Fulfillment = apps.get_model("accounts", "Fulfillment")
  Seller = apps.get_model("sellers", "Seller")
  fulfillment = Fulfillment.objects.filter(slug="default").first()
  if not fulfillment:
    fulfillment = Fulfillment.objects.create(slug="default", name="Основной фулфилмент")
  Seller.objects.filter(fulfillment__isnull=True).update(fulfillment=fulfillment)


class Migration(migrations.Migration):

  dependencies = [
    ("accounts", "0002_fulfillment"),
    ("sellers", "0007_seller_ozon_warehouse"),
  ]

  operations = [
    migrations.AddField(
      model_name="seller",
      name="fulfillment",
      field=models.ForeignKey(
        null=True,
        on_delete=django.db.models.deletion.CASCADE,
        related_name="sellers",
        to="accounts.fulfillment",
        verbose_name="Фулфилмент",
      ),
    ),
    migrations.RunPython(backfill_seller_fulfillment, migrations.RunPython.noop),
    migrations.AlterField(
      model_name="seller",
      name="fulfillment",
      field=models.ForeignKey(
        on_delete=django.db.models.deletion.CASCADE,
        related_name="sellers",
        to="accounts.fulfillment",
        verbose_name="Фулфилмент",
      ),
    ),
  ]
