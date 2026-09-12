from django.db import migrations, models


def rebuild_daily_quantities(apps, schema_editor):
  Product = apps.get_model("warehouse", "Product")
  from apps.warehouse.services.storage_stock_tracking import rebuild_product_daily_quantities

  for product in Product.objects.all().iterator():
    rebuild_product_daily_quantities(product)


class Migration(migrations.Migration):

  dependencies = [
    ("warehouse", "0012_wb_fact_intake"),
  ]

  operations = [
    migrations.AddField(
      model_name="product",
      name="positive_stock_since",
      field=models.DateField(
        blank=True,
        help_text="Первый день текущего непрерывного периода с положительным остатком",
        null=True,
        verbose_name="Остаток > 0 с даты",
      ),
    ),
    migrations.CreateModel(
      name="ProductDailyQuantity",
      fields=[
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
        ("date", models.DateField(verbose_name="Дата")),
        ("quantity", models.PositiveIntegerField(default=0, verbose_name="Остаток CRM")),
        (
          "product",
          models.ForeignKey(
            on_delete=models.deletion.CASCADE,
            related_name="daily_quantities",
            to="warehouse.product",
          ),
        ),
      ],
      options={
        "verbose_name": "Остаток товара по дням",
        "verbose_name_plural": "Остатки товаров по дням",
        "indexes": [models.Index(fields=["product", "date"])],
        "unique_together": {("product", "date")},
      },
    ),
    migrations.RunPython(rebuild_daily_quantities, migrations.RunPython.noop),
  ]
