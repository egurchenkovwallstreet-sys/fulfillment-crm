from django.db import migrations, models


class Migration(migrations.Migration):

  dependencies = [
    ("orders", "0012_picklistitem_nullable_cell_product"),
  ]

  operations = [
    migrations.AddField(
      model_name="ozonposting",
      name="marking_codes",
      field=models.JSONField(blank=True, default=list, verbose_name="Коды Честного знака"),
    ),
    migrations.AddField(
      model_name="ozonposting",
      name="delivery_method_id",
      field=models.BigIntegerField(
        blank=True, db_index=True, null=True, verbose_name="ID метода доставки Ozon"
      ),
    ),
    migrations.AddField(
      model_name="ozonposting",
      name="carriage_id",
      field=models.BigIntegerField(
        blank=True, db_index=True, null=True, verbose_name="ID отгрузки Ozon"
      ),
    ),
    migrations.AddField(
      model_name="ozonposting",
      name="products_json",
      field=models.JSONField(blank=True, default=list, verbose_name="Товары отправления"),
    ),
  ]
