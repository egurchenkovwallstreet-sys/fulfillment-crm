from django.db import migrations, models


class Migration(migrations.Migration):
  dependencies = [
    ("orders", "0014_ozon_posting_shipped_at"),
  ]

  operations = [
    migrations.AddField(
      model_name="picklist",
      name="marketplace",
      field=models.CharField(
        choices=[("wb", "Wildberries"), ("ozon", "Ozon")],
        db_index=True,
        default="wb",
        max_length=10,
        verbose_name="Маркетплейс",
      ),
    ),
    migrations.AddField(
      model_name="ozonposting",
      name="pick_list",
      field=models.ForeignKey(
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="ozon_postings",
        to="orders.picklist",
      ),
    ),
  ]
