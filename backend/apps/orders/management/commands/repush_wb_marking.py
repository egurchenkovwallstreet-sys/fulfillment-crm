from django.core.management.base import BaseCommand

from apps.orders.services.marking_verification import repair_assembly_marking_wb
from apps.sellers.models import Seller


class Command(BaseCommand):
  help = "Сверить ЧЗ с WB и дослать коды для заказов на сборке (после старого бага async)."

  def add_arguments(self, parser):
    parser.add_argument("--seller-id", type=int, required=True, help="ID селлера в CRM")

  def handle(self, *args, **options):
    seller = Seller.objects.filter(pk=options["seller_id"]).first()
    if not seller:
      self.stderr.write(self.style.ERROR(f"Селлер {options['seller_id']} не найден"))
      return

    result = repair_assembly_marking_wb(seller, force=True)
    self.stdout.write(
      self.style.SUCCESS(
        f"Готово: сверено {result['synced']}, сброшено ложных verified {result['downgraded']}, "
        f"дослано в WB {result['repushed']}.",
      ),
    )
