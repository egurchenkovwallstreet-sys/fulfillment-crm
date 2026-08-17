import django.db.models.deletion
from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("accounts", "0001_initial"),
        ("sellers", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Cell",
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
                    "number",
                    models.CharField(
                        max_length=50,
                        unique=True,
                        verbose_name="Номер ячейки",
                    ),
                ),
                (
                    "is_occupied",
                    models.BooleanField(default=False, verbose_name="Занята"),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Ячейка",
                "verbose_name_plural": "Ячейки",
                "ordering": ["number"],
            },
        ),
        migrations.CreateModel(
            name="PriceGroup",
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
                ("name", models.CharField(max_length=100, verbose_name="Название группы")),
                (
                    "processing_price",
                    models.DecimalField(
                        decimal_places=2,
                        default=Decimal("0.00"),
                        max_digits=10,
                        verbose_name="Стоимость обработки за единицу",
                    ),
                ),
                (
                    "sort_order",
                    models.PositiveSmallIntegerField(default=0, verbose_name="Порядок"),
                ),
            ],
            options={
                "verbose_name": "Ценовая группа",
                "verbose_name_plural": "Ценовые группы",
                "ordering": ["sort_order", "name"],
            },
        ),
        migrations.CreateModel(
            name="Product",
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
                ("barcode", models.CharField(max_length=100, verbose_name="Баркод")),
                (
                    "name",
                    models.CharField(
                        blank=True,
                        max_length=500,
                        verbose_name="Название",
                    ),
                ),
                (
                    "individual_price",
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        max_digits=10,
                        null=True,
                        verbose_name="Индивидуальная стоимость",
                    ),
                ),
                (
                    "requires_marking",
                    models.BooleanField(
                        default=False,
                        verbose_name="Требует маркировку (ЧЗ)",
                    ),
                ),
                (
                    "quantity",
                    models.PositiveIntegerField(default=0, verbose_name="Остаток"),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "cell",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="products",
                        to="warehouse.cell",
                        verbose_name="Ячейка",
                    ),
                ),
                (
                    "price_group",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="products",
                        to="warehouse.pricegroup",
                        verbose_name="Ценовая группа",
                    ),
                ),
                (
                    "seller",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="products",
                        to="sellers.seller",
                        verbose_name="Селлер",
                    ),
                ),
            ],
            options={
                "verbose_name": "Товар",
                "verbose_name_plural": "Товары",
            },
        ),
        migrations.CreateModel(
            name="StockOperation",
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
                    "operation_type",
                    models.CharField(
                        choices=[
                            ("intake", "Приёмка"),
                            ("shipment", "Списание (поставка)"),
                            ("return", "Возврат"),
                            ("adjustment", "Корректировка"),
                        ],
                        max_length=20,
                    ),
                ),
                ("quantity", models.IntegerField(verbose_name="Количество")),
                ("comment", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "performed_by",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="stock_operations",
                        to="accounts.user",
                    ),
                ),
                (
                    "product",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="stock_operations",
                        to="warehouse.product",
                    ),
                ),
            ],
            options={
                "verbose_name": "Складская операция",
                "verbose_name_plural": "Складские операции",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="product",
            index=models.Index(fields=["barcode"], name="warehouse_p_barcode_8a0f0d_idx"),
        ),
        migrations.AddIndex(
            model_name="product",
            index=models.Index(
                fields=["seller", "barcode"],
                name="warehouse_p_seller__f8e2a1_idx",
            ),
        ),
        migrations.AlterUniqueTogether(
            name="product",
            unique_together={("seller", "barcode")},
        ),
    ]
