from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

  dependencies = [
    ("warehouse", "0016_wb_fact_intake_warehouse_snapshot"),
  ]

  operations = [
    migrations.CreateModel(
      name="ProductBarcodeAlias",
      fields=[
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
        ("barcode", models.CharField(db_index=True, max_length=100, verbose_name="Баркод")),
        ("created_at", models.DateTimeField(auto_now_add=True)),
        (
          "product",
          models.ForeignKey(
            on_delete=django.db.models.deletion.CASCADE,
            related_name="barcode_aliases",
            to="warehouse.product",
            verbose_name="Товар",
          ),
        ),
      ],
      options={
        "verbose_name": "Доп. баркод товара",
        "verbose_name_plural": "Доп. баркоды товаров",
        "indexes": [
          models.Index(fields=["barcode"], name="warehouse_p_barcode_6a8f2a_idx"),
          models.Index(fields=["product", "barcode"], name="warehouse_p_product_9c4b1d_idx"),
        ],
        "unique_together": {("product", "barcode")},
      },
    ),
  ]
