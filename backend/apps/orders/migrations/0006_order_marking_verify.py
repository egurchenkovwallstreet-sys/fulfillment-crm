from django.db import migrations, models


class Migration(migrations.Migration):

  dependencies = [
    ("orders", "0005_order_wb_created_at"),
  ]

  operations = [
    migrations.AddField(
      model_name="order",
      name="marking_verify_status",
      field=models.CharField(
        blank=True,
        db_index=True,
        max_length=20,
        verbose_name="Статус проверки ЧЗ в WB",
      ),
    ),
    migrations.AddField(
      model_name="order",
      name="marking_verify_error",
      field=models.TextField(blank=True, verbose_name="Ошибка проверки ЧЗ"),
    ),
  ]
