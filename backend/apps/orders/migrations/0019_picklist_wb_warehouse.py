from django.db import migrations, models


class Migration(migrations.Migration):

  dependencies = [
    ("orders", "0018_order_sticker_scan_code"),
  ]

  operations = [
    migrations.AddField(
      model_name="picklist",
      name="wb_warehouse_id",
      field=models.BigIntegerField(
        blank=True,
        db_index=True,
        null=True,
        verbose_name="ID склада WB",
      ),
    ),
    migrations.AddField(
      model_name="picklist",
      name="warehouse_name",
      field=models.CharField(
        blank=True,
        max_length=200,
        verbose_name="Название склада",
      ),
    ),
  ]
