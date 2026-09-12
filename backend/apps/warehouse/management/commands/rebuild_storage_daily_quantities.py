from django.core.management.base import BaseCommand
from django.db.models.signals import post_save, pre_save

from apps.warehouse.models import Product
from apps.warehouse.services.storage_stock_tracking import rebuild_all_product_daily_quantities
from apps.warehouse.signals import product_post_save, product_track_previous_quantity


class Command(BaseCommand):
  help = "Восстановить снимки CRM-остатков по дням из StockOperation (для начисления хранения)."

  def handle(self, *args, **options):
    post_save.disconnect(product_post_save, sender=Product)
    pre_save.disconnect(product_track_previous_quantity, sender=Product)
    try:
      result = rebuild_all_product_daily_quantities()
    finally:
      pre_save.connect(product_track_previous_quantity, sender=Product)
      post_save.connect(product_post_save, sender=Product)

    self.stdout.write(
      self.style.SUCCESS(
        f"Готово: {result['products']} товаров, {result['snapshots']} снимков"
      )
    )
