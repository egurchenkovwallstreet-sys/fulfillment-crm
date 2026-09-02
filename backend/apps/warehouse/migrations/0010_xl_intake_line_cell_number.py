from django.db import migrations, models


class Migration(migrations.Migration):
  dependencies = [
    ("warehouse", "0009_article_intake_push_lock"),
  ]

  operations = [
    migrations.AddField(
      model_name="xlintakeline",
      name="cell_number",
      field=models.CharField(blank=True, default="", max_length=50, verbose_name="Ячейка"),
    ),
  ]
