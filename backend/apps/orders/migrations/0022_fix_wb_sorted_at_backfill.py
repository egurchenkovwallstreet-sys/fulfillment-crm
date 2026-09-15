from django.db import migrations


def fix_wb_sorted_at_backfill(apps, schema_editor):
  Order = apps.get_model("orders", "Order")
  Supply = apps.get_model("orders", "Supply")

  for order in Order.objects.filter(wb_sorted_at__isnull=False).iterator(chunk_size=500):
    scan_times = list(
      Supply.objects.filter(orders=order, wb_scanned_at__isnull=False).values_list(
        "wb_scanned_at",
        flat=True,
      )
    )
    clear = False
    if scan_times and order.wb_sorted_at < min(scan_times):
      clear = True
    if (
      order.in_delivery_at
      and order.wb_sorted_at == order.in_delivery_at
    ):
      clear = True
    if clear:
      Order.objects.filter(pk=order.pk).update(wb_sorted_at=None)


class Migration(migrations.Migration):

  dependencies = [
    ("orders", "0021_order_wb_sorted_at"),
  ]

  operations = [
    migrations.RunPython(fix_wb_sorted_at_backfill, migrations.RunPython.noop),
  ]
