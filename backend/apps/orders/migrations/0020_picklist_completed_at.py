from django.db import migrations, models


class Migration(migrations.Migration):

  dependencies = [
    ("orders", "0019_picklist_wb_warehouse"),
  ]

  operations = [
    migrations.AddField(
      model_name="picklist",
      name="completed_at",
      field=models.DateTimeField(blank=True, null=True, verbose_name="Архивирован"),
    ),
  ]
