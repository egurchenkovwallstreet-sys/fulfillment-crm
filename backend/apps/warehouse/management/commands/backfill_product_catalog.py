from django.core.management.base import BaseCommand

from apps.sellers.models import Seller
from apps.warehouse.services.wb_product_sync import refresh_all_sellers_products_from_wb


class Command(BaseCommand):
  help = "Разово подтянуть фото, размеры и названия для всех товаров из каталога МП"

  def add_arguments(self, parser):
    parser.add_argument(
      "--seller-id",
      type=int,
      help="Только один селлер (по умолчанию — все активные)",
    )

  def handle(self, *args, **options):
    seller_id = options.get("seller_id")
    if seller_id:
      seller = Seller.objects.filter(pk=seller_id, is_active=True).first()
      if not seller:
        self.stderr.write(self.style.ERROR(f"Селлер {seller_id} не найден"))
        return
      from apps.warehouse.services.wb_product_sync import refresh_seller_products_from_wb

      result = refresh_seller_products_from_wb(seller)
      self.stdout.write(
        self.style.SUCCESS(
          f"{seller.company_name}: обновлено {result.updated} из {result.total}, "
          f"не найдено {result.not_found}"
        )
      )
      if result.error:
        self.stderr.write(self.style.ERROR(result.error))
      return

    payload = refresh_all_sellers_products_from_wb()
    for row in payload["results"]:
      self.stdout.write(
        self.style.SUCCESS(
          f"Селлер {row['seller_id']}: обновлено {row['updated']} из {row['total']}, "
          f"не найдено {row['not_found']}"
        )
      )
    for row in payload["errors"]:
      self.stderr.write(
        self.style.ERROR(
          f"Селлер {row['seller_id']}: {row['error']} "
          f"(обновлено {row['updated']} из {row['total']})"
        )
      )
