from django.db import migrations, models


class Migration(migrations.Migration):
  dependencies = [
    ("orders", "0007_supply_wb_scanned_at"),
  ]

  operations = [
    migrations.AddField(
      model_name="order",
      name="assembly_hidden",
      field=models.BooleanField(db_index=True, default=False, verbose_name="Скрыт из сборки FBS"),
    ),
  ]
