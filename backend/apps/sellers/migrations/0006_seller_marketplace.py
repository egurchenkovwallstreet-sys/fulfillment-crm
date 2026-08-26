from django.db import migrations, models


class Migration(migrations.Migration):

  dependencies = [
    ("sellers", "0005_sellerinvite"),
  ]

  operations = [
    migrations.AddField(
      model_name="seller",
      name="wb_enabled",
      field=models.BooleanField(default=True, verbose_name="Wildberries"),
    ),
    migrations.AddField(
      model_name="seller",
      name="ozon_enabled",
      field=models.BooleanField(default=False, verbose_name="Ozon"),
    ),
    migrations.AddField(
      model_name="seller",
      name="ozon_client_id",
      field=models.CharField(blank=True, max_length=64, verbose_name="Ozon Client-Id"),
    ),
    migrations.AddField(
      model_name="seller",
      name="ozon_api_key_encrypted",
      field=models.TextField(blank=True, verbose_name="Ozon Api-Key (зашифрован)"),
    ),
    migrations.AddField(
      model_name="seller",
      name="ozon_count_new",
      field=models.PositiveIntegerField(default=0, verbose_name="Ozon: новые"),
    ),
    migrations.AddField(
      model_name="seller",
      name="ozon_count_assembly",
      field=models.PositiveIntegerField(default=0, verbose_name="Ozon: на сборке"),
    ),
    migrations.AddField(
      model_name="seller",
      name="ozon_count_delivery",
      field=models.PositiveIntegerField(default=0, verbose_name="Ozon: в доставке"),
    ),
    migrations.AddField(
      model_name="seller",
      name="ozon_counts_synced_at",
      field=models.DateTimeField(blank=True, null=True, verbose_name="Ozon: счётчики обновлены"),
    ),
  ]
