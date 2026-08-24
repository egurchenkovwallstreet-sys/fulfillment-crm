from django.db import migrations, models


class Migration(migrations.Migration):

  dependencies = [
    ("orders", "0006_order_marking_verify"),
  ]

  operations = [
    migrations.AddField(
      model_name="supply",
      name="wb_scanned_at",
      field=models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="ШК поставки отсканирован на складе WB",
      ),
    ),
  ]
