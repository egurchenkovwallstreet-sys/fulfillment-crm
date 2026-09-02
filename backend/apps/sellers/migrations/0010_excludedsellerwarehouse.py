from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
  dependencies = [
    ("sellers", "0009_seller_assembly_workflow_mode"),
  ]

  operations = [
    migrations.CreateModel(
      name="ExcludedSellerWarehouse",
      fields=[
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
        (
          "marketplace",
          models.CharField(
            choices=[("wb", "Wildberries"), ("ozon", "Ozon")],
            max_length=10,
            verbose_name="Маркетплейс",
          ),
        ),
        ("warehouse_external_id", models.BigIntegerField(verbose_name="ID склада в ЛК")),
        ("excluded_at", models.DateTimeField(auto_now_add=True)),
        (
          "seller",
          models.ForeignKey(
            on_delete=django.db.models.deletion.CASCADE,
            related_name="excluded_warehouses",
            to="sellers.seller",
          ),
        ),
      ],
      options={
        "verbose_name": "Исключённый склад селлера",
        "verbose_name_plural": "Исключённые склады селлеров",
      },
    ),
    migrations.AddConstraint(
      model_name="excludedsellerwarehouse",
      constraint=models.UniqueConstraint(
        fields=("seller", "marketplace", "warehouse_external_id"),
        name="uniq_excluded_seller_warehouse",
      ),
    ),
  ]
