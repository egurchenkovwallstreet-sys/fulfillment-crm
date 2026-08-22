from django.db import migrations, models


class Migration(migrations.Migration):

  dependencies = [
    ("orders", "0004_order_wb_warehouse_id"),
  ]

  operations = [
    migrations.AddField(
      model_name="order",
      name="wb_created_at",
      field=models.DateTimeField(blank=True, db_index=True, null=True, verbose_name="Дата заказа WB"),
    ),
  ]
