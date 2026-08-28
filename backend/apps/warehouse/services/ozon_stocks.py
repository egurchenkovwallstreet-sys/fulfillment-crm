"""Отправка остатков CRM на склад Ozon FBS."""
from __future__ import annotations

from apps.integrations.marketplace import OZON
from apps.integrations.models import AuditLog
from apps.integrations.ozon_client import OzonApiError
from apps.orders.services.ozon_counts import OzonCountsError, ozon_client_for_seller
from apps.sellers.models import Seller, SellerOzonWarehouse
from apps.warehouse.models import Product


class OzonStockError(Exception):
  pass


def push_ozon_crm_stocks(seller: Seller, warehouse_id: int, *, user=None) -> dict:
  warehouse = SellerOzonWarehouse.objects.filter(pk=warehouse_id, seller=seller).first()
  if not warehouse:
    raise OzonStockError("Склад Ozon не найден. Обновите склады из Ozon.")

  products = list(
    Product.objects.filter(seller=seller, marketplace=OZON).order_by("cell__number", "id")
  )
  if not products:
    raise OzonStockError("Нет товаров Ozon в CRM. Сначала подключите каталог.")

  stocks = []
  skipped = 0
  for product in products:
    offer_id = (product.vendor_code or product.barcode or "").strip()
    if not offer_id:
      skipped += 1
      continue
    stocks.append({
      "offer_id": offer_id,
      "stock": int(product.quantity or 0),
      "warehouse_id": warehouse.ozon_warehouse_id,
    })
  if not stocks:
    raise OzonStockError("Нет артикулов (offer_id) для отправки на Ozon")

  try:
    client = ozon_client_for_seller(seller)
    raw = client.update_stocks(stocks)
  except (OzonCountsError, OzonApiError) as exc:
    raise OzonStockError(str(exc)) from exc

  updated = 0
  errors = []
  for row in raw:
    ok = row.get("updated")
    if ok is True or str(ok).lower() == "true":
      updated += 1
      continue
    errors.append({
      "offer_id": row.get("offer_id") or "",
      "error": str(row.get("errors") or row.get("error") or row)[:240],
    })
  if not raw:
    updated = len(stocks)

  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.OTHER,
    message=f"Остатки CRM → склад Ozon «{warehouse.name or warehouse.ozon_warehouse_id}»: {updated} шт.",
    details={"updated": updated, "errors": len(errors), "skipped": skipped},
  )
  return {
    "success": True,
    "warehouse_id": warehouse.id,
    "warehouse_name": warehouse.name or f"Склад #{warehouse.ozon_warehouse_id}",
    "sent": len(stocks),
    "updated": updated,
    "skipped": skipped,
    "errors": errors[:20],
    "error_count": len(errors),
    "message": (
      f"На склад Ozon «{warehouse.name or warehouse.ozon_warehouse_id}» отправлено {len(stocks)} остатков. "
      f"Принято: {updated}."
      + (f" Ошибок: {len(errors)}." if errors else "")
    ),
  }
