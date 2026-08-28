import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

  dependencies = [
    ("orders", "0011_order_seller_wb_unique"),
  ]

  operations = [
    migrations.AlterField(
      model_name="picklistitem",
      name="cell",
      field=models.ForeignKey(
        blank=True,
        null=True,
        on_delete=django.db.models.deletion.PROTECT,
        to="warehouse.cell",
      ),
    ),
    migrations.AlterField(
      model_name="picklistitem",
      name="product",
      field=models.ForeignKey(
        blank=True,
        null=True,
        on_delete=django.db.models.deletion.PROTECT,
        to="warehouse.product",
      ),
    ),
  ]
