"""Вспомогательные функции для селлеров."""
from __future__ import annotations

from django.core.exceptions import ObjectDoesNotExist

from apps.sellers.models import Seller


def seller_has_user_account(seller: Seller) -> bool:
  try:
    seller.user_account
  except ObjectDoesNotExist:
    return False
  return True


def seller_username(seller: Seller) -> str | None:
  try:
    return seller.user_account.username
  except ObjectDoesNotExist:
    return None
