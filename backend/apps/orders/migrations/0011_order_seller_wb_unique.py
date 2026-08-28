# Generated manually — wb_order_id unique per seller, not globally

from django.db import migrations, models


class Migration(migrations.Migration):

  dependencies = [
    ("orders", "0010_ozon_posting"),
  ]

  operations = [
    migrations.AlterField(
      model_name="order",
      name="wb_order_id",
      field=models.BigIntegerField(verbose_name="ID заказа WB"),
    ),
    migrations.AddConstraint(
      model_name="order",
      constraint=models.UniqueConstraint(
        fields=("seller", "wb_order_id"),
        name="uniq_order_seller_wb_id",
      ),
    ),
  ]
