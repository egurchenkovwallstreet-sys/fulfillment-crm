from django.core.management.base import BaseCommand
from django.db.models.signals import post_save, pre_save

from apps.warehouse.models import Product
from apps.warehouse.services.storage_stock_tracking import rebuild_all_product_daily_quantities
from apps.warehouse.signals import product_record_daily_quantity, product_track_previous_quantity


class Command(BaseCommand):
  help = "Восстановить снимки CRM-остатков по дням из StockOperation (для начисления хранения)."

  def add_arguments(self, parser):
    parser.add_argument(
      "--no-accrue",
      action="store_true",
      help="Только снимки, без пересчёта начислений хранения",
    )

  def handle(self, *args, **options):
    post_save.disconnect(product_record_daily_quantity, sender=Product)
    pre_save.disconnect(product_track_previous_quantity, sender=Product)
    try:
      result = rebuild_all_product_daily_quantities()
    finally:
      pre_save.connect(product_track_previous_quantity, sender=Product)
      post_save.connect(product_record_daily_quantity, sender=Product)

    self.stdout.write(
      self.style.SUCCESS(
        f"Снимки: {result['products']} товаров, {result['snapshots']} записей"
      )
    )

    if options["no_accrue"]:
      return

    from apps.sellers.services.liter_billing import accrue_daily_storage_all_sellers

    accrue_result = accrue_daily_storage_all_sellers()
    self.stdout.write(
      self.style.SUCCESS(
        f"Хранение: {accrue_result['sellers']} селлеров, {accrue_result['products']} начислений "
        f"за {accrue_result['date']}"
      )
    )
