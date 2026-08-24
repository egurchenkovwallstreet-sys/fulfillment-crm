from django.core.management.base import BaseCommand
from django.db import transaction

from apps.orders.models import Order, PickList, PickListItem
from apps.warehouse.models import Cell, Product, ProductWarehouseStock, StockOperation


class Command(BaseCommand):
  help = (
    "Удалить все ячейки и товары CRM, обнулить складские остатки. "
    "Заказы сохраняются, ссылка на товар снимается."
  )

  def add_arguments(self, parser):
    parser.add_argument(
      "--confirm",
      action="store_true",
      help="Обязательный флаг: подтвердить полный сброс склада",
    )

  def handle(self, *args, **options):
    if not options["confirm"]:
      self.stderr.write(
        self.style.ERROR(
          "Добавьте --confirm для выполнения: "
          "python manage.py reset_warehouse --confirm",
        ),
      )
      return

    stats = {
      "pick_list_items": PickListItem.objects.count(),
      "pick_lists": PickList.objects.count(),
      "orders_with_product": Order.objects.filter(product__isnull=False).count(),
      "warehouse_stocks": ProductWarehouseStock.objects.count(),
      "stock_operations": StockOperation.objects.count(),
      "products": Product.objects.count(),
      "cells": Cell.objects.count(),
    }

    self.stdout.write("Текущее состояние:")
    for key, value in stats.items():
      self.stdout.write(f"  {key}: {value}")

    with transaction.atomic():
      deleted_items, _ = PickListItem.objects.all().delete()
      deleted_lists, _ = PickList.objects.all().delete()
      orders_updated = Order.objects.filter(product__isnull=False).update(product=None)
      deleted_products, product_details = Product.objects.all().delete()
      deleted_cells, _ = Cell.objects.all().delete()

    self.stdout.write(self.style.SUCCESS("Сброс выполнен:"))
    self.stdout.write(f"  позиций листов подбора: {deleted_items}")
    self.stdout.write(f"  листов подбора: {deleted_lists}")
    self.stdout.write(f"  заказов (снята привязка к товару): {orders_updated}")
    self.stdout.write(f"  товаров (и связанных остатков/операций): {deleted_products}")
    if product_details:
      for model, count in sorted(product_details.items()):
        if count:
          self.stdout.write(f"    — {model}: {count}")
    self.stdout.write(f"  ячеек: {deleted_cells}")
