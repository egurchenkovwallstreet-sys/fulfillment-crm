from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from apps.sellers.services.calendar_periods import today_local
from apps.warehouse.models import Product
from apps.warehouse.services.storage_stock_tracking import (
  record_product_daily_quantity,
  touch_positive_stock_since,
)


@receiver(pre_save, sender=Product)
def product_track_previous_quantity(sender, instance: Product, **kwargs):
  if instance.pk:
    previous = (
      Product.objects.filter(pk=instance.pk)
      .values_list("quantity", flat=True)
      .first()
    )
    instance._storage_prev_quantity = int(previous or 0)
  else:
    instance._storage_prev_quantity = 0


@receiver(post_save, sender=Product)
def product_record_daily_quantity(sender, instance: Product, created: bool, **kwargs):
  previous_qty = int(getattr(instance, "_storage_prev_quantity", 0))
  new_qty = int(instance.quantity or 0)
  on_date = today_local()

  record_product_daily_quantity(instance, quantity=new_qty, on_date=on_date)
  if created or previous_qty != new_qty:
    touch_positive_stock_since(instance, previous_qty, new_qty, on_date=on_date)
