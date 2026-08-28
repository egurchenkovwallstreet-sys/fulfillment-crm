# Generated manually — attach price groups to default fulfillment

import django.db.models.deletion
from django.db import migrations, models


def backfill_pricegroup_fulfillment(apps, schema_editor):
  Fulfillment = apps.get_model("accounts", "Fulfillment")
  PriceGroup = apps.get_model("warehouse", "PriceGroup")
  fulfillment = Fulfillment.objects.filter(slug="default").first()
  if not fulfillment:
    fulfillment = Fulfillment.objects.create(slug="default", name="Основной фулфилмент")
  PriceGroup.objects.filter(fulfillment__isnull=True).update(fulfillment=fulfillment)


class Migration(migrations.Migration):

  dependencies = [
    ("accounts", "0002_fulfillment"),
    ("warehouse", "0005_cell_marketplace"),
  ]

  operations = [
    migrations.AddField(
      model_name="pricegroup",
      name="fulfillment",
      field=models.ForeignKey(
        null=True,
        on_delete=django.db.models.deletion.CASCADE,
        related_name="price_groups",
        to="accounts.fulfillment",
        verbose_name="Фулфилмент",
      ),
    ),
    migrations.RunPython(backfill_pricegroup_fulfillment, migrations.RunPython.noop),
    migrations.AlterField(
      model_name="pricegroup",
      name="fulfillment",
      field=models.ForeignKey(
        on_delete=django.db.models.deletion.CASCADE,
        related_name="price_groups",
        to="accounts.fulfillment",
        verbose_name="Фулфилмент",
      ),
    ),
  ]
