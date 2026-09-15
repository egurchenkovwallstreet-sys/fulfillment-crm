from django.db import migrations, models


def backfill_wb_sorted_at(apps, schema_editor):
  Order = apps.get_model("orders", "Order")
  qs = Order.objects.filter(
    wb_sorted_at__isnull=True,
    in_delivery_at__isnull=False,
    status__in=("shipped", "in_delivery", "cancelled"),
  )
  for order in qs.iterator(chunk_size=500):
    order.wb_sorted_at = order.in_delivery_at
    order.save(update_fields=["wb_sorted_at"])


class Migration(migrations.Migration):

  dependencies = [
    ("orders", "0020_picklist_completed_at"),
  ]

  operations = [
    migrations.AddField(
      model_name="order",
      name="wb_sorted_at",
      field=models.DateTimeField(
        blank=True,
        db_index=True,
        null=True,
        verbose_name="Отсортирован на СЦ WB",
      ),
    ),
    migrations.RunPython(backfill_wb_sorted_at, migrations.RunPython.noop),
  ]
