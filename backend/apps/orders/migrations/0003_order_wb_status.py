from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0002_order_stickers"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="wb_status",
            field=models.CharField(blank=True, max_length=30, verbose_name="Статус WB (wb)"),
        ),
        migrations.AddField(
            model_name="order",
            name="wb_supplier_status",
            field=models.CharField(
                blank=True,
                db_index=True,
                max_length=30,
                verbose_name="Статус WB (supplier)",
            ),
        ),
        migrations.AlterField(
            model_name="order",
            name="status",
            field=models.CharField(
                choices=[
                    ("new", "Новый"),
                    ("in_picking", "В подборе"),
                    ("assembled", "Собран"),
                    ("label_printed", "Этикетка напечатана"),
                    ("marked", "Маркировка привязана"),
                    ("in_supply", "В поставке"),
                    ("in_delivery", "В доставке"),
                    ("shipped", "Отправлен"),
                    ("cancelled", "Отменён"),
                ],
                default="new",
                max_length=20,
            ),
        ),
        migrations.AddIndex(
            model_name="order",
            index=models.Index(fields=["seller", "wb_supplier_status"], name="orders_orde_seller__a1b2c3_idx"),
        ),
    ]
