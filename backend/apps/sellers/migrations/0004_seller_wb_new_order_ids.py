from django.db import migrations, models


class Migration(migrations.Migration):

  dependencies = [
    ("sellers", "0003_sellerwarehouse"),
  ]

  operations = [
    migrations.AddField(
      model_name="seller",
      name="wb_new_order_ids",
      field=models.JSONField(
        blank=True,
        default=list,
        verbose_name="WB: ID новых заказов (последний sync)",
      ),
    ),
  ]
