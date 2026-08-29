from django.db import migrations, models


class Migration(migrations.Migration):

  dependencies = [
    ("warehouse", "0008_article_intake"),
  ]

  operations = [
    migrations.AddField(
      model_name="articleintakesession",
      name="marketplace_pushed_at",
      field=models.DateTimeField(blank=True, null=True, verbose_name="Выгрузка на MP"),
    ),
    migrations.AddField(
      model_name="articleintakesession",
      name="active_group_key",
      field=models.CharField(blank=True, default="", max_length=255, verbose_name="Текущая группа"),
    ),
  ]
