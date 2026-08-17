import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("accounts", "0001_initial"),
        ("sellers", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="AuditLog",
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
                    "action_type",
                    models.CharField(
                        choices=[
                            ("intake", "Приёмка"),
                            ("assembly", "Сборка"),
                            ("label_print", "Печать этикетки"),
                            ("marking", "Привязка ЧЗ"),
                            ("supply", "Поставка"),
                            ("return", "Возврат"),
                            ("wb_sync", "Синхронизация WB"),
                            ("api_error", "Ошибка API"),
                            ("other", "Прочее"),
                        ],
                        max_length=20,
                    ),
                ),
                ("message", models.TextField()),
                ("details", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "seller",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="audit_logs",
                        to="sellers.seller",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="audit_logs",
                        to="accounts.user",
                    ),
                ),
            ],
            options={
                "verbose_name": "Журнал действий",
                "verbose_name_plural": "Журнал действий",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="auditlog",
            index=models.Index(
                fields=["action_type", "created_at"],
                name="integration_action__7c8d9e_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="auditlog",
            index=models.Index(
                fields=["seller", "created_at"],
                name="integration_seller__1a2b3c_idx",
            ),
        ),
    ]
