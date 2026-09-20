from django.core.management.base import BaseCommand

from apps.accounts.models import Fulfillment
from apps.sellers.services.admin_billing_cache import rebuild_admin_billing_cache


class Command(BaseCommand):
  help = "Пересчитать кеш статистики отгрузок для всех фулфилментов (WB и Ozon)."

  def handle(self, *args, **options):
    fulfillments = list(Fulfillment.objects.all().order_by("id"))
    if not fulfillments:
      self.stdout.write(self.style.WARNING("No fulfillments found"))
      return

    for fulfillment in fulfillments:
      for marketplace in ("wb", "ozon"):
        result = rebuild_admin_billing_cache(
          fulfillment_id=fulfillment.id,
          marketplace=marketplace,
        )
        self.stdout.write(
          f"fulfillment={fulfillment.id} marketplace={marketplace} result={result}",
        )
