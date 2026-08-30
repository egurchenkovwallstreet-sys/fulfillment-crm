from django.db import migrations, models


class Migration(migrations.Migration):
  dependencies = [
    ("sellers", "0008_seller_fulfillment"),
  ]

  operations = [
    migrations.AddField(
      model_name="seller",
      name="assembly_workflow_mode",
      field=models.CharField(
        choices=[("scan", "Пошаговый скан"), ("batch", "Лента стикеров")],
        default="scan",
        max_length=10,
        verbose_name="Режим сборки FBS",
      ),
    ),
  ]
