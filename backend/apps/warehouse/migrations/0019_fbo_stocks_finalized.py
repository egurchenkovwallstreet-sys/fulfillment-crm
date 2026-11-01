from django.db import migrations, models


class Migration(migrations.Migration):

  dependencies = [
    ("warehouse", "0018_fbo_assembly"),
  ]

  operations = [
    migrations.AddField(
      model_name="fboassemblysession",
      name="stocks_finalized_at",
      field=models.DateTimeField(blank=True, null=True, verbose_name="Остатки CRM/WB списаны"),
    ),
  ]
