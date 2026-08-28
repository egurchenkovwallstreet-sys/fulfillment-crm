from django.db import migrations, models


def sync_applied_quantities(apps, schema_editor):
  XlIntakeSession = apps.get_model("warehouse", "XlIntakeSession")
  XlIntakeLine = apps.get_model("warehouse", "XlIntakeLine")
  for session in XlIntakeSession.objects.filter(status="applied"):
    for line in XlIntakeLine.objects.filter(session=session):
      if line.applied_quantity < line.quantity:
        line.applied_quantity = line.quantity
        line.save(update_fields=["applied_quantity"])


class Migration(migrations.Migration):

  dependencies = [
    ("warehouse", "0006_pricegroup_fulfillment"),
  ]

  operations = [
    migrations.AddField(
      model_name="xlintakeline",
      name="applied_quantity",
      field=models.PositiveIntegerField(default=0, verbose_name="Уже применено в CRM"),
    ),
    migrations.AddField(
      model_name="xlintakesession",
      name="completed_at",
      field=models.DateTimeField(blank=True, null=True),
    ),
    migrations.AlterField(
      model_name="xlintakesession",
      name="status",
      field=models.CharField(
        choices=[
          ("scanning", "Сканирование"),
          ("saved", "Сохранена"),
          ("applied", "Ячейки созданы"),
          ("completed", "Завершена"),
        ],
        db_index=True,
        default="scanning",
        max_length=20,
      ),
    ),
    migrations.RunPython(sync_applied_quantities, migrations.RunPython.noop),
  ]
