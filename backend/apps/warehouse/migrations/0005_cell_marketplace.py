from django.db import migrations, models


class Migration(migrations.Migration):

  dependencies = [
    ("warehouse", "0004_xl_intake"),
  ]

  operations = [
    migrations.AddField(
      model_name="cell",
      name="marketplace",
      field=models.CharField(
        choices=[("wb", "Wildberries"), ("ozon", "Ozon")],
        db_index=True,
        default="wb",
        max_length=8,
        verbose_name="Маркетплейс",
      ),
    ),
    migrations.AlterUniqueTogether(
      name="cell",
      unique_together={("seller", "marketplace", "number")},
    ),
    migrations.AddField(
      model_name="product",
      name="marketplace",
      field=models.CharField(
        choices=[("wb", "Wildberries"), ("ozon", "Ozon")],
        db_index=True,
        default="wb",
        max_length=8,
        verbose_name="Маркетплейс",
      ),
    ),
    migrations.AlterUniqueTogether(
      name="product",
      unique_together={("seller", "marketplace", "barcode")},
    ),
    migrations.AddField(
      model_name="xlintakesession",
      name="marketplace",
      field=models.CharField(
        choices=[("wb", "Wildberries"), ("ozon", "Ozon")],
        db_index=True,
        default="wb",
        max_length=8,
        verbose_name="Маркетплейс",
      ),
    ),
  ]
