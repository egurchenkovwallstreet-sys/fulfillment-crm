"""Tenant scoping helpers for multi-fulfillment isolation."""
from __future__ import annotations

from django.utils.text import slugify

from apps.accounts.models import Fulfillment, User
from apps.sellers.models import Seller
from apps.warehouse.models import PriceGroup

DEFAULT_FULFILLMENT_SLUG = "default"
DEFAULT_FULFILLMENT_NAME = "Основной фулфилмент"


def get_or_create_default_fulfillment() -> Fulfillment:
  fulfillment, _ = Fulfillment.objects.get_or_create(
    slug=DEFAULT_FULFILLMENT_SLUG,
    defaults={"name": DEFAULT_FULFILLMENT_NAME},
  )
  return fulfillment


def unique_fulfillment_slug(name: str) -> str:
  base = slugify(name, allow_unicode=True) or "fulfillment"
  slug = base[:90]
  counter = 1
  while Fulfillment.objects.filter(slug=slug).exists():
    suffix = f"-{counter}"
    slug = f"{base[: 90 - len(suffix)]}{suffix}"
    counter += 1
  return slug


def get_user_fulfillment(user: User | None) -> Fulfillment | None:
  if not user or not user.is_authenticated:
    return None
  if user.role == User.Role.SELLER:
    if not user.seller_id:
      return None
    seller = (
      Seller.objects.select_related("fulfillment")
      .filter(pk=user.seller_id)
      .first()
    )
    return seller.fulfillment if seller else None
  if user.fulfillment_id:
    return user.fulfillment
  return None


def sellers_for_user(user: User, queryset=None):
  qs = queryset if queryset is not None else Seller.objects.all()
  fulfillment = get_user_fulfillment(user)
  if not fulfillment:
    return qs.none()
  return qs.filter(fulfillment=fulfillment)


def get_seller_for_user(user: User, seller_id, *, active_only: bool = False) -> Seller | None:
  qs = sellers_for_user(user).filter(pk=seller_id)
  if active_only:
    qs = qs.filter(is_active=True)
  return qs.select_related("fulfillment").first()


def price_groups_for_user(user: User):
  fulfillment = get_user_fulfillment(user)
  if not fulfillment:
    return PriceGroup.objects.none()
  return PriceGroup.objects.filter(fulfillment=fulfillment).order_by("sort_order", "name")


def fulfillment_for_staff_user(user: User) -> Fulfillment | None:
  """Fulfillment for admin/manager actions (create seller, staff, price group)."""
  if user.role == User.Role.SELLER:
    return None
  return get_user_fulfillment(user)
