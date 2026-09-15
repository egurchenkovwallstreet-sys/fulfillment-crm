from datetime import timedelta

from django.db import migrations, models


CANCEL_WB_STATUSES = frozenset({
  "canceled",
  "canceled_by_client",
  "declined_by_client",
  "canceled_by_carrier",
  "cancel",
})

STICKER_SCANNED_WB_STATUSES = frozenset({
  "sorted",
  "accepted_by_carrier",
  "sent_to_carrier",
  "postponed_delivery",
  "sold",
  "ready_for_pickup",
  "defect",
})


def backfill_wb_sticker_scanned_at(apps, schema_editor):
  Order = apps.get_model("orders", "Order")
  Supply = apps.get_model("orders", "Supply")

  qs = (
    Order.objects.filter(
      wb_supplier_status="complete",
      wb_sorted_at__isnull=True,
    )
    .exclude(wb_status__in=CANCEL_WB_STATUSES)
    .exclude(wb_status="waiting")
    .exclude(wb_status="")
  )

  for order in qs.iterator(chunk_size=500):
    wb_status = (order.wb_status or "").strip()
    if wb_status not in STICKER_SCANNED_WB_STATUSES and wb_status:
      continue

    scan_times = list(
      Supply.objects.filter(orders=order, wb_scanned_at__isnull=False).values_list(
        "wb_scanned_at",
        flat=True,
      )
    )
    candidate = order.updated_at
    if scan_times:
      min_scan = min(scan_times)
      if candidate <= min_scan:
        candidate = min_scan + timedelta(minutes=1)

    Order.objects.filter(pk=order.pk).update(wb_sorted_at=candidate)


class Migration(migrations.Migration):

  dependencies = [
    ("orders", "0022_fix_wb_sorted_at_backfill"),
  ]

  operations = [
    migrations.AlterField(
      model_name="order",
      name="wb_sorted_at",
      field=models.DateTimeField(
        blank=True,
        db_index=True,
        null=True,
        verbose_name="Стикер отсканирован на СЦ WB",
      ),
    ),
    migrations.RunPython(backfill_wb_sticker_scanned_at, migrations.RunPython.noop),
  ]
