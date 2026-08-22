from django.db import migrations, models
import uuid
import django.db.models.deletion


class Migration(migrations.Migration):

  dependencies = [
    ("sellers", "0004_seller_wb_new_order_ids"),
  ]

  operations = [
    migrations.CreateModel(
      name="SellerInvite",
      fields=[
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
        ("token", models.UUIDField(default=uuid.uuid4, editable=False, unique=True, verbose_name="Токен")),
        ("is_active", models.BooleanField(default=True, verbose_name="Активна")),
        ("used_at", models.DateTimeField(blank=True, null=True, verbose_name="Использована")),
        ("created_at", models.DateTimeField(auto_now_add=True)),
        ("updated_at", models.DateTimeField(auto_now=True)),
        (
          "seller",
          models.OneToOneField(
            on_delete=django.db.models.deletion.CASCADE,
            related_name="invite",
            to="sellers.seller",
          ),
        ),
      ],
      options={
        "verbose_name": "Приглашение селлера",
        "verbose_name_plural": "Приглашения селлеров",
      },
    ),
  ]
