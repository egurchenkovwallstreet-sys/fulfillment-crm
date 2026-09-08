from django.db import migrations, models


class Migration(migrations.Migration):

  dependencies = [
    ("sellers", "0011_seller_liter_pricing"),
  ]

  operations = [
    migrations.AddField(
      model_name="excludedsellerwarehouse",
      name="name",
      field=models.CharField(
        blank=True,
        default="",
        max_length=255,
        verbose_name="Название на момент удаления",
      ),
    ),
  ]
