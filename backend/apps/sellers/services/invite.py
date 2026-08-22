from __future__ import annotations

import uuid

from django.utils import timezone

from apps.sellers.models import Seller, SellerInvite


def ensure_seller_invite(seller: Seller) -> SellerInvite:
  """Создаёт запись приглашения, если её ещё нет."""
  invite, _ = SellerInvite.objects.get_or_create(seller=seller)
  return invite


def issue_seller_invite(seller: Seller) -> SellerInvite:
  """Выдаёт активную одноразовую ссылку (при необходимости — новую)."""
  invite, _ = SellerInvite.objects.get_or_create(seller=seller)
  if not invite.is_active:
    invite.token = uuid.uuid4()
    invite.is_active = True
    invite.used_at = None
    invite.save(update_fields=["token", "is_active", "used_at", "updated_at"])
  return invite


def deactivate_invite(invite: SellerInvite) -> None:
  invite.is_active = False
  invite.used_at = timezone.now()
  invite.save(update_fields=["is_active", "used_at", "updated_at"])


def get_invite_by_token(token) -> SellerInvite | None:
  try:
    return SellerInvite.objects.select_related("seller").get(token=token, is_active=True)
  except SellerInvite.DoesNotExist:
    return None
