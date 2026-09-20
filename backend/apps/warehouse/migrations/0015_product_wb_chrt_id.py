from django.db import migrations, models


class Migration(migrations.Migration):

  dependencies = [
    ("warehouse", "0014_xl_list_intake"),
  ]

  operations = [
    migrations.AddField(
      model_name="product",
      name="wb_chrt_id",
      field=models.BigIntegerField(
        blank=True,
        db_index=True,
        help_text="Нужен для остатков FBS — WB больше не принимает баркод (sku) в API остатков",
        null=True,
        verbose_name="ID размера WB (chrtId)",
      ),
    ),
  ]
