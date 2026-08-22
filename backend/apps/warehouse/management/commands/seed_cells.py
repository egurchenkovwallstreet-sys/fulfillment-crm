from django.core.management.base import BaseCommand

from apps.sellers.models import Seller
from apps.warehouse.models import Cell


class Command(BaseCommand):
  help = "Создать пустые ячейки 1..N для селлера (обычно не нужно — ячейки создаются при приёмке)"

  def add_arguments(self, parser):
    parser.add_argument("--seller-id", type=int, required=True)
    parser.add_argument("--count", type=int, default=50)

  def handle(self, *args, **options):
    seller_id = options["seller_id"]
    count = options["count"]

    seller = Seller.objects.filter(pk=seller_id).first()
    if not seller:
      self.stderr.write(self.style.ERROR(f"Селлер {seller_id} не найден"))
      return

    existing = set(
      Cell.objects.filter(seller=seller).values_list("number", flat=True),
    )
    to_create = [
      Cell(seller=seller, number=str(i), is_occupied=False)
      for i in range(1, count + 1)
      if str(i) not in existing
    ]
    if not to_create:
      self.stdout.write(self.style.WARNING("Все ячейки уже существуют — пропуск"))
      return

    Cell.objects.bulk_create(to_create)
    self.stdout.write(
      self.style.SUCCESS(f"Создано ячеек для {seller.company_name}: {len(to_create)}"),
    )
