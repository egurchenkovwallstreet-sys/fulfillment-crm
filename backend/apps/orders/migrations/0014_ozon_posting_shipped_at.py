from django.db import migrations, models
from django.utils import timezone


def backfill_shipped_at(apps, schema_editor):
  OzonPosting = apps.get_model("orders", "OzonPosting")
  for posting in OzonPosting.objects.filter(
    crm_stage="in_delivery",
    shipped_at__isnull=True,
  ).iterator():
    posting.shipped_at = posting.updated_at or timezone.now()
    posting.save(update_fields=["shipped_at"])


class Migration(migrations.Migration):

  dependencies = [
    ("orders", "0013_ozon_posting_label_act"),
  ]

  operations = [
    migrations.AddField(
      model_name="ozonposting",
      name="shipped_at",
      field=models.DateTimeField(
        blank=True,
        db_index=True,
        null=True,
        verbose_name="Передано к отгрузке",
      ),
    ),
    migrations.RunPython(backfill_shipped_at, migrations.RunPython.noop),
  ]
