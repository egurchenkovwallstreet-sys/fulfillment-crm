from django.db import migrations, models


class Migration(migrations.Migration):
  dependencies = [
    ("orders", "0017_order_in_delivery_at"),
  ]

  operations = [
    migrations.AddField(
      model_name="order",
      name="sticker_scan_code",
      field=models.CharField(
        blank=True,
        help_text="Закодированное значение из API WB (поле barcode) — то, что читает QR на стикере",
        max_length=64,
        verbose_name="QR-код стикера WB",
      ),
    ),
  ]
