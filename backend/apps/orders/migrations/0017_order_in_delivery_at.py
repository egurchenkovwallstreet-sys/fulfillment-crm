from django.db import migrations, models


class Migration(migrations.Migration):

  dependencies = [
    ("orders", "0016_off_crm_shipment"),
  ]

  operations = [
    migrations.AddField(
      model_name="order",
      name="in_delivery_at",
      field=models.DateTimeField(
        blank=True,
        db_index=True,
        null=True,
        verbose_name="Передан в доставку",
      ),
    ),
  ]
