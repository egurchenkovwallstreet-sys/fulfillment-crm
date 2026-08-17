from django.core.management.base import BaseCommand

from apps.warehouse.models import Cell


class Command(BaseCommand):
  help = "Создать ячейки склада (1..N), если их ещё нет"

  def add_arguments(self, parser):
    parser.add_argument("--count", type=int, default=50)

  def handle(self, *args, **options):
    count = options["count"]
    if Cell.objects.exists():
      self.stdout.write(self.style.WARNING("Ячейки уже существуют — пропуск"))
      return

    cells = [Cell(number=str(i), is_occupied=False) for i in range(1, count + 1)]
    Cell.objects.bulk_create(cells)
    self.stdout.write(self.style.SUCCESS(f"Создано ячеек: {count}"))
