from django.core.management.base import BaseCommand
from django.db import transaction

from apps.orders.models import PickList
from apps.warehouse.models import Cell, Product, ProductWarehouseStock, StockOperation
from apps.warehouse.services.cell_delete import force_delete_cells


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
      "pick_lists": PickList.objects.count(),
      "warehouse_stocks": ProductWarehouseStock.objects.count(),
      "stock_operations": StockOperation.objects.count(),
      "products": Product.objects.count(),
      "cells": Cell.objects.count(),
    }

    self.stdout.write("Текущее состояние:")
    for key, value in stats.items():
      self.stdout.write(f"  {key}: {value}")

    with transaction.atomic():
      deleted_lists, _ = PickList.objects.all().delete()
      orphan_products = Product.objects.filter(cell__isnull=True).count()
      if orphan_products:
        Product.objects.filter(cell__isnull=True).delete()
      cell_stats = force_delete_cells(Cell.objects.all())

    self.stdout.write(self.style.SUCCESS("Сброс выполнен:"))
    self.stdout.write(f"  листов подбора: {deleted_lists}")
    self.stdout.write(f"  позиций листов подбора: {cell_stats['pick_list_items']}")
    self.stdout.write(f"  заказов (снята привязка к товару): {cell_stats['orders_unlinked']}")
    self.stdout.write(f"  товаров: {cell_stats['products']}")
    if orphan_products:
      self.stdout.write(f"  товаров без ячейки: {orphan_products}")
    self.stdout.write(f"  ячеек: {cell_stats['cells']}")
