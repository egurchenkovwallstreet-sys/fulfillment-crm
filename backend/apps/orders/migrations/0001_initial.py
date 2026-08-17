import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("sellers", "0001_initial"),
        ("warehouse", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Order",
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
                    "wb_order_id",
                    models.BigIntegerField(unique=True, verbose_name="ID заказа WB"),
                ),
                (
                    "barcode",
                    models.CharField(max_length=100, verbose_name="Баркод заказа"),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("new", "Новый"),
                            ("in_picking", "В подборе"),
                            ("assembled", "Собран"),
                            ("label_printed", "Этикетка напечатана"),
                            ("marked", "Маркировка привязана"),
                            ("in_supply", "В поставке"),
                            ("shipped", "Отправлен"),
                            ("cancelled", "Отменён"),
                        ],
                        default="new",
                        max_length=20,
                    ),
                ),
                (
                    "marking_code",
                    models.CharField(
                        blank=True,
                        max_length=500,
                        verbose_name="Код Честного знака",
                    ),
                ),
                (
                    "marking_bound",
                    models.BooleanField(
                        default=False,
                        verbose_name="Маркировка привязана",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "product",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="orders",
                        to="warehouse.product",
                    ),
                ),
                (
                    "seller",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="orders",
                        to="sellers.seller",
                    ),
                ),
            ],
            options={
                "verbose_name": "Заказ",
                "verbose_name_plural": "Заказы",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="PickList",
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
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("is_completed", models.BooleanField(default=False)),
                (
                    "seller",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="pick_lists",
                        to="sellers.seller",
                    ),
                ),
            ],
            options={
                "verbose_name": "Лист подбора",
                "verbose_name_plural": "Листы подбора",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="Supply",
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
                    "wb_supply_id",
                    models.CharField(
                        blank=True,
                        max_length=100,
                        verbose_name="ID поставки WB",
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("forming", "Формируется"),
                            ("ready", "Готова"),
                            ("confirmed", "Подтверждена WB"),
                            ("shipped", "Отправлена"),
                        ],
                        default="forming",
                        max_length=20,
                    ),
                ),
                (
                    "supply_barcode_printed",
                    models.BooleanField(
                        default=False,
                        verbose_name="ШК поставки распечатан",
                    ),
                ),
                (
                    "stock_deducted",
                    models.BooleanField(
                        default=False,
                        verbose_name="Остатки списаны",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "orders",
                    models.ManyToManyField(
                        blank=True,
                        related_name="supplies",
                        to="orders.order",
                    ),
                ),
                (
                    "seller",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="supplies",
                        to="sellers.seller",
                    ),
                ),
            ],
            options={
                "verbose_name": "Поставка",
                "verbose_name_plural": "Поставки",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="PickListItem",
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
                ("barcode", models.CharField(max_length=100)),
                (
                    "quantity",
                    models.PositiveIntegerField(verbose_name="Количество собрать"),
                ),
                (
                    "picked_quantity",
                    models.PositiveIntegerField(default=0, verbose_name="Собрано"),
                ),
                (
                    "cell",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to="warehouse.cell",
                    ),
                ),
                (
                    "pick_list",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="items",
                        to="orders.picklist",
                    ),
                ),
                (
                    "product",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to="warehouse.product",
                    ),
                ),
            ],
            options={
                "verbose_name": "Позиция листа подбора",
                "verbose_name_plural": "Позиции листа подбора",
            },
        ),
        migrations.AddIndex(
            model_name="order",
            index=models.Index(
                fields=["wb_order_id"],
                name="orders_orde_wb_orde_6b8f2a_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="order",
            index=models.Index(
                fields=["seller", "status"],
                name="orders_orde_seller__a1b2c3_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="order",
            index=models.Index(
                fields=["barcode"],
                name="orders_orde_barcode_d4e5f6_idx",
            ),
        ),
    ]
