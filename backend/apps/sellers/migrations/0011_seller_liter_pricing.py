from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

  dependencies = [
    ("sellers", "0010_excludedsellerwarehouse"),
    ("warehouse", "0010_xl_intake_line_cell_number"),
    ("orders", "0018_order_sticker_scan_code"),
  ]

  operations = [
    migrations.AddField(
      model_name="seller",
      name="pricing_mode",
      field=models.CharField(
        choices=[("per_unit", "По штукам"), ("per_liter", "По литражу")],
        default="per_unit",
        max_length=12,
        verbose_name="Режим тарификации",
      ),
    ),
    migrations.AddField(
      model_name="seller",
      name="first_liter_shipment_price",
      field=models.DecimalField(decimal_places=2, default=Decimal("10.00"), max_digits=10, verbose_name="Отгрузка: 1-й литр, ₽"),
    ),
    migrations.AddField(
      model_name="seller",
      name="next_liter_shipment_price",
      field=models.DecimalField(decimal_places=2, default=Decimal("6.00"), max_digits=10, verbose_name="Отгрузка: каждый след. литр, ₽"),
    ),
    migrations.AddField(
      model_name="seller",
      name="marking_surcharge_per_unit",
      field=models.DecimalField(decimal_places=2, default=Decimal("5.00"), max_digits=10, verbose_name="Надбавка за ЧЗ, ₽/шт"),
    ),
    migrations.AddField(
      model_name="seller",
      name="storage_tariff_per_liter_month",
      field=models.DecimalField(decimal_places=2, default=Decimal("1.00"), max_digits=10, verbose_name="Хранение, ₽/л/мес"),
    ),
    migrations.CreateModel(
      name="DailyStorageCharge",
      fields=[
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
        ("charge_date", models.DateField(verbose_name="Дата")),
        ("quantity", models.PositiveIntegerField(verbose_name="Шт на складе")),
        ("volume_liters", models.DecimalField(decimal_places=2, max_digits=10, verbose_name="Литры на шт")),
        ("amount", models.DecimalField(decimal_places=2, max_digits=12, verbose_name="Сумма, ₽")),
        ("created_at", models.DateTimeField(auto_now_add=True)),
        ("product", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="daily_storage_charges", to="warehouse.product")),
        ("seller", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="daily_storage_charges", to="sellers.seller")),
      ],
      options={
        "verbose_name": "Начисление хранения",
        "verbose_name_plural": "Начисления хранения",
        "unique_together": {("seller", "product", "charge_date")},
      },
    ),
    migrations.CreateModel(
      name="ShipmentLiterCharge",
      fields=[
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
        ("barcode", models.CharField(db_index=True, max_length=100, verbose_name="Баркод")),
        ("marketplace", models.CharField(default="wb", max_length=8, verbose_name="Маркетплейс")),
        ("charge_date", models.DateField(verbose_name="Дата")),
        ("volume_liters", models.DecimalField(decimal_places=2, max_digits=10, verbose_name="Литры")),
        ("has_marking", models.BooleanField(default=False, verbose_name="ЧЗ")),
        ("amount", models.DecimalField(decimal_places=2, max_digits=12, verbose_name="Сумма, ₽")),
        ("created_at", models.DateTimeField(auto_now_add=True)),
        ("order", models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, related_name="liter_shipment_charges", to="orders.order")),
        ("ozon_posting", models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, related_name="liter_shipment_charges", to="orders.ozonposting")),
        ("product", models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, related_name="shipment_liter_charges", to="warehouse.product")),
        ("seller", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="shipment_liter_charges", to="sellers.seller")),
      ],
      options={
        "verbose_name": "Отгрузка по литражу",
        "verbose_name_plural": "Отгрузки по литражу",
      },
    ),
    migrations.AddIndex(
      model_name="dailystoragecharge",
      index=models.Index(fields=["seller", "charge_date"], name="sellers_dai_seller__8a0f0d_idx"),
    ),
    migrations.AddIndex(
      model_name="shipmentlitercharge",
      index=models.Index(fields=["seller", "charge_date"], name="sellers_shi_seller__f6d2a1_idx"),
    ),
  ]
