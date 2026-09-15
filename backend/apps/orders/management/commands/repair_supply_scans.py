"""Принудительно подтянуть scanDt поставок WB в CRM."""
from django.core.management.base import BaseCommand

from apps.orders.services.sync_orders import sync_all_delivery_scans, sync_delivery_scans_for_seller
from apps.sellers.models import Seller


class Command(BaseCommand):
  help = "Синхронизировать scanDt отсканированных поставок WB (все селлеры или один)"

  def add_arguments(self, parser):
    parser.add_argument("--seller-id", type=int, help="ID селлера (иначе все WB)")
    parser.add_argument("--company", type=str, help="Часть названия компании")

  def handle(self, *args, **options):
    seller_id = options.get("seller_id")
    company = (options.get("company") or "").strip()

    if seller_id or company:
      qs = Seller.objects.filter(is_active=True, wb_enabled=True)
      if seller_id:
        qs = qs.filter(pk=seller_id)
      if company:
        qs = qs.filter(company_name__icontains=company)
      seller = qs.first()
      if not seller:
        self.stderr.write("Селлер не найден")
        return
      result = sync_delivery_scans_for_seller(seller)
      scan = result.get("supply_scan") or {}
      self.stdout.write(
        f"{seller.company_name}: pending={scan.get('pending_supplies', '?')} "
        f"scanDt_in_list={scan.get('scan_dt_in_list', '?')} "
        f"scanned={scan.get('supplies_scanned', 0)} "
        f"orders_closed={scan.get('orders_closed', 0)}",
      )
      return

    payload = sync_all_delivery_scans()
    totals = payload.get("totals") or {}
    self.stdout.write(
      f"Итого: scanned={totals.get('supplies_scanned', 0)} "
      f"orders_closed={totals.get('orders_closed', 0)} "
      f"errors={len(payload.get('errors') or [])}",
    )
    for row in payload.get("results") or []:
      scan = row.get("supply_scan") or {}
      if scan.get("supplies_scanned") or scan.get("pending_supplies"):
        self.stdout.write(
          f"  seller {row.get('seller_id')}: pending={scan.get('pending_supplies')} "
          f"scanned={scan.get('supplies_scanned')} closed={scan.get('orders_closed')}",
        )
