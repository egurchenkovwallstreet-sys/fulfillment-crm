from django.db import transaction
from django.utils import timezone

from apps.integrations.models import AuditLog
from apps.integrations.wb_client import WBApiError, WBClient
from apps.integrations.wb_crypto import TokenCryptoError, decrypt_token
from apps.orders.models import Order
from apps.orders.services.sync_statuses import sync_order_statuses_for_seller
from apps.sellers.models import Seller
from apps.warehouse.models import Product


class SyncError(Exception):
  pass


def _get_seller_token(seller: Seller) -> str:
  if not seller.wb_api_token_encrypted:
    raise SyncError(f"У селлера «{seller.company_name}» не задан токен WB")
  try:
    return decrypt_token(seller.wb_api_token_encrypted)
  except TokenCryptoError as exc:
    raise SyncError(str(exc)) from exc


def _link_product(seller: Seller, barcode: str) -> Product | None:
  return Product.objects.filter(seller=seller, barcode=barcode).first()


@transaction.atomic
def sync_orders_for_seller(seller: Seller, *, user=None) -> dict:
  if not seller.is_active:
    raise SyncError("Селлер неактивен")

  token = _get_seller_token(seller)
  client = WBClient(token)

  try:
    fetch_result = client.fetch_new_orders()
  except WBApiError as exc:
    AuditLog.objects.create(
      user=user,
      seller=seller,
      action_type=AuditLog.ActionType.API_ERROR,
      message=f"Ошибка синхронизации заказов WB: {exc}",
      details={"status_code": exc.status_code},
    )
    raise SyncError(str(exc)) from exc

  wb_orders = fetch_result.orders
  created = 0
  updated = 0
  skipped = 0

  for wb_order in wb_orders:
    product = _link_product(seller, wb_order.barcode)
    order, was_created = Order.objects.update_or_create(
      wb_order_id=wb_order.wb_order_id,
      defaults={
        "seller": seller,
        "barcode": wb_order.barcode,
        "product": product,
      },
    )
    if was_created:
      created += 1
    else:
      updated += 1
    if not product:
      skipped += 1

  status_result = {"statuses_fetched": 0, "statuses_updated": 0}
  status_error = ""
  new_wb_ids = [wb_order.wb_order_id for wb_order in wb_orders]
  try:
    status_result = sync_order_statuses_for_seller(
      seller, client, user=user, new_wb_ids=new_wb_ids,
    )
  except WBApiError as exc:
    status_error = str(exc)

  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.WB_SYNC,
    message=(
      f"Синхронизация заказов WB: +{created}, обновлено {updated}, "
      f"из WB {fetch_result.raw_total}"
    ),
    details={
      "created": created,
      "updated": updated,
      "without_product": skipped,
      "skipped_no_barcode": fetch_result.skipped_no_barcode,
      "fetched": len(wb_orders),
      "raw_total": fetch_result.raw_total,
      "pages": fetch_result.pages,
      "statuses_fetched": status_result["statuses_fetched"],
      "statuses_updated": status_result["statuses_updated"],
      "status_error": status_error,
      "wb_counts": status_result.get("counts", {}),
      "live_counts": status_result.get("live_counts", {}),
      "reconcile": status_result.get("reconcile", {}),
      "synced_at": timezone.now().isoformat(),
    },
  )

  return {
    "seller_id": seller.id,
    "created": created,
    "updated": updated,
    "without_product": skipped,
    "fetched": len(wb_orders),
    "raw_total": fetch_result.raw_total,
    "skipped_no_barcode": fetch_result.skipped_no_barcode,
    "pages": fetch_result.pages,
    "statuses_fetched": status_result["statuses_fetched"],
    "statuses_updated": status_result["statuses_updated"],
    "status_error": status_error,
    "wb_counts": status_result.get("counts", {}),
    "live_counts": status_result.get("live_counts", {}),
    "reconcile": status_result.get("reconcile", {}),
  }


def sync_all_active_sellers(*, user=None) -> list[dict]:
  results = []
  errors = []
  for seller in Seller.objects.filter(is_active=True):
    try:
      results.append(sync_orders_for_seller(seller, user=user))
    except SyncError as exc:
      errors.append({"seller_id": seller.id, "error": str(exc)})
  return {"results": results, "errors": errors}
