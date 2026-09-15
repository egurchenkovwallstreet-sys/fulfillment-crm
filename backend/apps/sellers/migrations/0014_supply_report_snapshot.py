from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

  dependencies = [
    ("accounts", "0001_initial"),
    ("sellers", "0013_shipment_unit_charge"),
  ]

  operations = [
    migrations.CreateModel(
      name="SupplyReportSnapshot",
      fields=[
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
        ("month", models.DateField(verbose_name="Месяц (1-е число)")),
        ("payload", models.JSONField(default=dict)),
        ("built_at", models.DateTimeField(verbose_name="Собран")),
        (
          "fulfillment",
          models.ForeignKey(
            on_delete=django.db.models.deletion.CASCADE,
            related_name="supply_report_snapshots",
            to="accounts.fulfillment",
          ),
        ),
      ],
      options={
        "verbose_name": "Снимок отчёта по поставкам",
        "verbose_name_plural": "Снимки отчёта по поставкам",
        "indexes": [models.Index(fields=["fulfillment", "month"], name="sellers_sup_report_ff_month_idx")],
      },
    ),
    migrations.AddConstraint(
      model_name="supplyreportsnapshot",
      constraint=models.UniqueConstraint(
        fields=("fulfillment", "month"),
        name="sellers_supply_report_snapshot_uniq",
      ),
    ),
  ]
