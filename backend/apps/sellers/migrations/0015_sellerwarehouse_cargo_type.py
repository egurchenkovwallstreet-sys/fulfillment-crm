from django.db import migrations, models


class Migration(migrations.Migration):

  dependencies = [
    ("sellers", "0014_supply_report_snapshot"),
  ]

  operations = [
    migrations.AddField(
      model_name="sellerwarehouse",
      name="cargo_type",
      field=models.PositiveSmallIntegerField(
        blank=True,
        db_index=True,
        help_text="1=МГТ, 2=СГТ, 3=КГТ+ — из GET /api/v3/warehouses",
        null=True,
        verbose_name="Тип груза склада WB",
      ),
    ),
    migrations.AddField(
      model_name="sellerwarehouse",
      name="delivery_type",
      field=models.PositiveSmallIntegerField(
        blank=True,
        help_text="1=FBS — из GET /api/v3/warehouses",
        null=True,
        verbose_name="Тип доставки склада WB",
      ),
    ),
  ]
