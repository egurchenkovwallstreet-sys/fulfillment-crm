from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Seller",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "company_name",
                    models.CharField(
                        max_length=255,
                        verbose_name="ИП / название компании",
                    ),
                ),
                (
                    "wb_api_token_encrypted",
                    models.TextField(
                        blank=True,
                        verbose_name="WB API токен (зашифрован)",
                    ),
                ),
                ("is_active", models.BooleanField(default=True, verbose_name="Активен")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Селлер",
                "verbose_name_plural": "Селлеры",
                "ordering": ["company_name"],
            },
        ),
    ]
