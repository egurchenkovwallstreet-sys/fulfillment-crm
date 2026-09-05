from django.db import migrations, models


class Migration(migrations.Migration):

  dependencies = [
    ("warehouse", "0010_xl_intake_line_cell_number"),
  ]

  operations = [
    migrations.AddField(
      model_name="product",
      name="length_cm",
      field=models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True, verbose_name="Длина, см"),
    ),
    migrations.AddField(
      model_name="product",
      name="width_cm",
      field=models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True, verbose_name="Ширина, см"),
    ),
    migrations.AddField(
      model_name="product",
      name="height_cm",
      field=models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True, verbose_name="Высота, см"),
    ),
    migrations.AddField(
      model_name="product",
      name="volume_liters",
      field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True, verbose_name="Объём, л"),
    ),
  ]
