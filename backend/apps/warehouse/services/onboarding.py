"""Подтверждение мастера подключения селлера (сценарий 1)."""
from __future__ import annotations

from django.db import transaction

from apps.integrations.marketplace import WB, normalize_marketplace
from apps.integrations.models import AuditLog
from apps.sellers.models import Seller, SellerWarehouse
from apps.warehouse.models import Cell, Product, ProductWarehouseStock
from apps.warehouse.services.cells import refresh_cell_occupied


class OnboardingError(Exception):
  pass


@transaction.atomic
def confirm_onboarding(
  seller: Seller,
  items: list[dict],
  *,
  user=None,
  marketplace: str = WB,
) -> dict:
  """
  Создать ячейки и товары по подтверждённому плану.
  items — только включаемые баркоды с cell_number и wb_stock_*.
  """
  mp = normalize_marketplace(marketplace)
  created_products = 0
  updated_stocks = 0
  skipped = 0

  warehouses = {
    wh.id: wh
    for wh in SellerWarehouse.objects.filter(seller=seller, is_enabled=True)
  }

  for row in items:
    if row.get("excluded") or row.get("already_in_crm"):
      skipped += 1
      continue

    barcode = str(row.get("barcode") or "").strip()
    cell_number = str(row.get("cell_number") or "").strip()
    if not barcode or not cell_number:
      skipped += 1
      continue

    if Product.objects.filter(seller=seller, marketplace=mp, barcode=barcode).exists():
      skipped += 1
      continue

    cell, _ = Cell.objects.get_or_create(
      seller=seller,
      marketplace=mp,
      number=cell_number,
      defaults={"is_occupied": False},
    )

    product = Product.objects.create(
      seller=seller,
      marketplace=mp,
      barcode=barcode,
      name=str(row.get("title") or "").strip(),
      cell=cell,
      quantity=int(row.get("wb_stock_total") or 0) if str(row.get("wb_stock_total") or "0").lstrip("-").isdigit() else 0,
      requires_marking=bool(row.get("requires_marking")),
      wb_nm_id=int(row["wb_nm_id"]) if row.get("wb_nm_id") else None,
      vendor_code=str(row.get("vendor_code") or ""),
      tech_size=str(row.get("tech_size") or ""),
      wb_size=str(row.get("wb_size") or ""),
      photo_url=str(row.get("photo_url") or "") if str(row.get("photo_url") or "").startswith("http") else "",
    )
    refresh_cell_occupied(cell)
    created_products += 1

    if mp != WB:
      continue

    by_wh = row.get("wb_stock_by_warehouse") or {}
    for wh_pk, qty in by_wh.items():
      try:
        wh_id = int(wh_pk)
        qty_int = max(0, int(qty))
      except (TypeError, ValueError):
        continue
      warehouse = warehouses.get(wh_id)
      if not warehouse:
        continue
      ProductWarehouseStock.objects.update_or_create(
        product=product,
        seller_warehouse=warehouse,
        defaults={"quantity": qty_int},
      )
      updated_stocks += 1

  source = "Ozon" if mp != WB else "WB"
  AuditLog.objects.create(
    user=user,
    seller=seller,
    action_type=AuditLog.ActionType.INTAKE,
    message=f"Подключение каталога {source}: создано {created_products} товаров",
    details={
      "marketplace": mp,
      "created_products": created_products,
      "skipped": skipped,
      "warehouse_stocks": updated_stocks,
    },
  )

  return {
    "created_products": created_products,
    "skipped": skipped,
    "warehouse_stocks": updated_stocks,
  }
