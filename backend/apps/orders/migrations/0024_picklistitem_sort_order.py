from django.db import migrations, models


class Migration(migrations.Migration):

  dependencies = [
    ("orders", "0023_backfill_wb_sticker_scanned_at"),
  ]

  operations = [
    migrations.AddField(
      model_name="picklistitem",
      name="sort_order",
      field=models.PositiveIntegerField(db_index=True, default=0, verbose_name="Порядок в листе"),
    ),
  ]
