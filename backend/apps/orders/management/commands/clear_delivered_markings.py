from django.core.management.base import BaseCommand

from apps.orders.services.marking_cleanup import clear_all_delivered_marking_codes


class Command(BaseCommand):
  help = "Стереть все коды ЧЗ у заказов в доставке/отправленных (WB и Ozon)."

  def handle(self, *args, **options):
    result = clear_all_delivered_marking_codes()
    self.stdout.write(
      self.style.SUCCESS(
        f"Готово: WB заказов очищено {result['wb_cleared']}, "
        f"Ozon отправлений {result['ozon_cleared']}.",
      ),
    )
