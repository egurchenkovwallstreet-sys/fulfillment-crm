"""Данные для печати этикетки ячейки."""
from __future__ import annotations

from apps.integrations.marketplace import marketplace_label
from apps.warehouse.models import Product


def build_cell_label_data(product: Product) -> dict[str, str]:
  marketplace = product.marketplace or getattr(product.cell, "marketplace", "wb")
  return {
    "product_id": product.id,
    "seller_name": product.seller.company_name,
    "cell_number": product.cell.number,
    "barcode": product.barcode,
    "marketplace": marketplace,
    "marketplace_label": marketplace_label(marketplace),
  }
