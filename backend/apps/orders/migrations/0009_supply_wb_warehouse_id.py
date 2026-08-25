from django.db import migrations, models


class Migration(migrations.Migration):
  dependencies = [
    ("orders", "0008_order_assembly_hidden"),
  ]

  operations = [
    migrations.AddField(
      model_name="supply",
      name="wb_warehouse_id",
      field=models.BigIntegerField(
        blank=True,
        db_index=True,
        null=True,
        verbose_name="ID склада WB",
      ),
    ),
  ]
