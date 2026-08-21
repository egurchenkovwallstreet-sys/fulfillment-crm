"""Данные для печати этикетки ячейки."""
from __future__ import annotations

from apps.warehouse.models import Product


def build_cell_label_data(product: Product) -> dict[str, str]:
  return {
    "product_id": product.id,
    "seller_name": product.seller.company_name,
    "cell_number": product.cell.number,
    "barcode": product.barcode,
  }
