# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

  dependencies = [
    ("orders", "0003_order_wb_status"),
    ("sellers", "0003_sellerwarehouse"),
  ]

  operations = [
    migrations.AddField(
      model_name="order",
      name="wb_warehouse_id",
      field=models.BigIntegerField(blank=True, db_index=True, null=True, verbose_name="ID склада WB"),
    ),
  ]
