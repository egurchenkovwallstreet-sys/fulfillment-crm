from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

  dependencies = [
    ("sellers", "0001_initial"),
    ("warehouse", "0002_cell_per_seller"),
  ]

  operations = [
    migrations.AddField(
      model_name="product",
      name="photo_url",
      field=models.URLField(blank=True, max_length=500, verbose_name="Фото WB"),
    ),
    migrations.AddField(
      model_name="product",
      name="tech_size",
      field=models.CharField(blank=True, max_length=50, verbose_name="Размер (EU/тех.)"),
    ),
    migrations.AddField(
      model_name="product",
      name="vendor_code",
      field=models.CharField(blank=True, max_length=200, verbose_name="Артикул продавца"),
    ),
    migrations.AddField(
      model_name="product",
      name="wb_nm_id",
      field=models.BigIntegerField(
        blank=True,
        db_index=True,
        null=True,
        verbose_name="Артикул WB (nmID)",
      ),
    ),
    migrations.AddField(
      model_name="product",
      name="wb_size",
      field=models.CharField(blank=True, max_length=50, verbose_name="Размер (RU)"),
    ),
    migrations.CreateModel(
      name="ProductWarehouseStock",
      fields=[
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
        ("quantity", models.PositiveIntegerField(default=0, verbose_name="Остаток на складе WB")),
        ("updated_at", models.DateTimeField(auto_now=True)),
        (
          "product",
          models.ForeignKey(
            on_delete=django.db.models.deletion.CASCADE,
            related_name="warehouse_stocks",
            to="warehouse.product",
          ),
        ),
        (
          "seller_warehouse",
          models.ForeignKey(
            on_delete=django.db.models.deletion.CASCADE,
            related_name="product_stocks",
            to="sellers.sellerwarehouse",
          ),
        ),
      ],
      options={
        "verbose_name": "Остаток на складе WB",
        "verbose_name_plural": "Остатки на складах WB",
        "unique_together": {("product", "seller_warehouse")},
      },
    ),
  ]
