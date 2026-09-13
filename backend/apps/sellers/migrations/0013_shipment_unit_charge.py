from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

  dependencies = [
    ("orders", "0019_picklist_wb_warehouse"),
    ("sellers", "0012_excluded_warehouse_name"),
    ("warehouse", "0014_xl_list_intake"),
  ]

  operations = [
    migrations.CreateModel(
      name="ShipmentUnitCharge",
      fields=[
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
        ("barcode", models.CharField(db_index=True, max_length=100, verbose_name="Баркод")),
        ("marketplace", models.CharField(default="wb", max_length=8, verbose_name="Маркетплейс")),
        ("wb_order_id", models.BigIntegerField(blank=True, db_index=True, null=True, verbose_name="ID заказа WB")),
        ("charge_date", models.DateField(verbose_name="Дата")),
        ("quantity", models.PositiveIntegerField(default=1, verbose_name="Количество")),
        ("unit_price", models.DecimalField(decimal_places=2, max_digits=10, verbose_name="Тариф за ед., ₽")),
        ("amount", models.DecimalField(decimal_places=2, max_digits=12, verbose_name="Сумма, ₽")),
        ("created_at", models.DateTimeField(auto_now_add=True)),
        (
          "order",
          models.ForeignKey(
            blank=True,
            null=True,
            on_delete=django.db.models.deletion.SET_NULL,
            related_name="unit_shipment_charges",
            to="orders.order",
          ),
        ),
        (
          "ozon_posting",
          models.ForeignKey(
            blank=True,
            null=True,
            on_delete=django.db.models.deletion.SET_NULL,
            related_name="unit_shipment_charges",
            to="orders.ozonposting",
          ),
        ),
        (
          "product",
          models.ForeignKey(
            blank=True,
            null=True,
            on_delete=django.db.models.deletion.SET_NULL,
            related_name="shipment_unit_charges",
            to="warehouse.product",
          ),
        ),
        (
          "seller",
          models.ForeignKey(
            on_delete=django.db.models.deletion.CASCADE,
            related_name="shipment_unit_charges",
            to="sellers.seller",
          ),
        ),
      ],
      options={
        "verbose_name": "Отгрузка по тарифу (шт)",
        "verbose_name_plural": "Отгрузки по тарифу (шт)",
      },
    ),
    migrations.AddIndex(
      model_name="shipmentunitcharge",
      index=models.Index(fields=["seller", "charge_date"], name="sellers_shi_seller__a1b2c3_idx"),
    ),
    migrations.AddConstraint(
      model_name="shipmentunitcharge",
      constraint=models.UniqueConstraint(
        condition=models.Q(("wb_order_id__isnull", False)),
        fields=("seller", "wb_order_id"),
        name="sellers_unit_charge_wb_order_uniq",
      ),
    ),
    migrations.AddConstraint(
      model_name="shipmentunitcharge",
      constraint=models.UniqueConstraint(
        condition=models.Q(("ozon_posting__isnull", False)),
        fields=("ozon_posting",),
        name="sellers_unit_charge_ozon_posting_uniq",
      ),
    ),
  ]
