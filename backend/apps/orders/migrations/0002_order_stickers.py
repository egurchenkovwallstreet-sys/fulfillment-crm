import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="has_sticker",
            field=models.BooleanField(default=False, verbose_name="Стикер получен"),
        ),
        migrations.AddField(
            model_name="order",
            name="pick_list",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="orders",
                to="orders.picklist",
            ),
        ),
        migrations.AddField(
            model_name="order",
            name="sticker_fetched_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="order",
            name="sticker_file",
            field=models.TextField(blank=True, verbose_name="Стикер (base64)"),
        ),
        migrations.AddField(
            model_name="order",
            name="sticker_part_a",
            field=models.CharField(blank=True, max_length=50, verbose_name="Стикер partA"),
        ),
        migrations.AddField(
            model_name="order",
            name="sticker_part_b",
            field=models.CharField(blank=True, max_length=50, verbose_name="Стикер partB"),
        ),
    ]
