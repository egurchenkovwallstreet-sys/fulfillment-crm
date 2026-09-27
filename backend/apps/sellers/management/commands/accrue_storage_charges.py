from django.core.management.base import BaseCommand

from apps.sellers.services.liter_billing import accrue_daily_storage_all_sellers


class Command(BaseCommand):
  help = "Догнать ежедневные начисления хранения (DailyStorageCharge) по всем активным селлерам."

  def handle(self, *args, **options):
    result = accrue_daily_storage_all_sellers()
    self.stdout.write(
      self.style.SUCCESS(
        f"Хранение: дата={result['date']}, селлеров={result['sellers']}, "
        f"операций={result['products']}"
      )
    )
