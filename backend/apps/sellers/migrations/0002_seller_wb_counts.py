from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("sellers", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="seller",
            name="wb_count_assembly",
            field=models.PositiveIntegerField(default=0, verbose_name="WB: на сборке"),
        ),
        migrations.AddField(
            model_name="seller",
            name="wb_count_delivery",
            field=models.PositiveIntegerField(default=0, verbose_name="WB: в доставке"),
        ),
        migrations.AddField(
            model_name="seller",
            name="wb_count_new",
            field=models.PositiveIntegerField(default=0, verbose_name="WB: новые"),
        ),
        migrations.AddField(
            model_name="seller",
            name="wb_counts_synced_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="WB: счётчики обновлены"),
        ),
    ]
