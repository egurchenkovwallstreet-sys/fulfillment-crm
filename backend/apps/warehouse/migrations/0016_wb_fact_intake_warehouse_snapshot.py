from django.db import migrations, models
import django.db.models.deletion


def backfill_warehouse_snapshots(apps, schema_editor):
  WbFactIntakeSession = apps.get_model("warehouse", "WbFactIntakeSession")
  for session in WbFactIntakeSession.objects.select_related("warehouse").iterator():
    warehouse = session.warehouse
    if not warehouse:
      continue
    label = warehouse.name or f"Склад #{warehouse.wb_warehouse_id}"
    WbFactIntakeSession.objects.filter(pk=session.pk).update(
      warehouse_name_snapshot=label,
      wb_warehouse_id_snapshot=warehouse.wb_warehouse_id,
    )


class Migration(migrations.Migration):
  dependencies = [
    ("warehouse", "0015_product_wb_chrt_id"),
  ]

  operations = [
    migrations.AddField(
      model_name="wbfactintakesession",
      name="warehouse_name_snapshot",
      field=models.CharField(
        blank=True,
        help_text="Сохраняется при удалении склада из CRM для истории приёмок",
        max_length=255,
        verbose_name="Название склада (снимок)",
      ),
    ),
    migrations.AddField(
      model_name="wbfactintakesession",
      name="wb_warehouse_id_snapshot",
      field=models.BigIntegerField(
        blank=True,
        null=True,
        verbose_name="ID склада WB (снимок)",
      ),
    ),
    migrations.AlterField(
      model_name="wbfactintakesession",
      name="warehouse",
      field=models.ForeignKey(
        blank=True,
        null=True,
        on_delete=django.db.models.deletion.SET_NULL,
        related_name="wb_fact_intake_sessions",
        to="sellers.sellerwarehouse",
        verbose_name="Склад FBS WB",
      ),
    ),
    migrations.RunPython(backfill_warehouse_snapshots, migrations.RunPython.noop),
  ]
