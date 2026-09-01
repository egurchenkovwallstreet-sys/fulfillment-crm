from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

  dependencies = [
    ("orders", "0015_ozon_posting_pick_list"),
    migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ("sellers", "0003_sellerwarehouse"),
  ]

  operations = [
    migrations.CreateModel(
      name="OffCrmShipment",
      fields=[
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
        ("wb_order_id", models.BigIntegerField(db_index=True, verbose_name="ID заказа WB")),
        ("barcode", models.CharField(db_index=True, max_length=100, verbose_name="Баркод")),
        ("sticker_part_a", models.CharField(max_length=50, verbose_name="Стикер partA")),
        ("sticker_part_b", models.CharField(max_length=50, verbose_name="Стикер partB")),
        ("sticker_number", models.CharField(blank=True, max_length=120, verbose_name="Номер стикера")),
        ("wb_supply_id", models.CharField(blank=True, db_index=True, max_length=100, verbose_name="ID поставки WB")),
        ("wb_warehouse_id", models.BigIntegerField(blank=True, db_index=True, null=True, verbose_name="ID склада WB")),
        ("warehouse_name", models.CharField(blank=True, max_length=200, verbose_name="Склад")),
        ("quantity", models.PositiveIntegerField(default=1, verbose_name="Количество")),
        ("shipped_at", models.DateTimeField(blank=True, db_index=True, null=True, verbose_name="Отгружено в WB")),
        ("detected_at", models.DateTimeField(auto_now_add=True, verbose_name="Обнаружено")),
        (
          "status",
          models.CharField(
            choices=[("pending", "Ожидает решения"), ("deducted", "Списано"), ("skipped", "Не списывать")],
            db_index=True,
            default="pending",
            max_length=20,
          ),
        ),
        ("resolved_at", models.DateTimeField(blank=True, null=True)),
        (
          "crm_order",
          models.ForeignKey(
            blank=True,
            null=True,
            on_delete=django.db.models.deletion.SET_NULL,
            related_name="off_crm_shipments",
            to="orders.order",
          ),
        ),
        (
          "resolved_by",
          models.ForeignKey(
            blank=True,
            null=True,
            on_delete=django.db.models.deletion.SET_NULL,
            related_name="resolved_off_crm_shipments",
            to=settings.AUTH_USER_MODEL,
          ),
        ),
        (
          "seller",
          models.ForeignKey(
            on_delete=django.db.models.deletion.CASCADE,
            related_name="off_crm_shipments",
            to="sellers.seller",
          ),
        ),
      ],
      options={
        "verbose_name": "Отгрузка вне CRM",
        "verbose_name_plural": "Отгрузки вне CRM",
        "ordering": ["-shipped_at", "-detected_at"],
      },
    ),
    migrations.AddIndex(
      model_name="offcrmshipment",
      index=models.Index(fields=["seller", "status"], name="orders_off__seller__a1b2c3_idx"),
    ),
    migrations.AddConstraint(
      model_name="offcrmshipment",
      constraint=models.UniqueConstraint(
        fields=("seller", "sticker_part_a", "sticker_part_b"),
        name="uniq_off_crm_sticker_per_seller",
      ),
    ),
  ]
