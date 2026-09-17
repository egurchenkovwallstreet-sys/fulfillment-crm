from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase

from apps.accounts.models import Fulfillment
from apps.orders.models import Order, Supply
from apps.orders.services.supply_flow import (
  SHIPPING_PREFETCH_NEAR_DONE_THRESHOLD,
  _shipping_prefetch_lock_key,
  maybe_prefetch_shipping_points_after_assembly_progress,
)
from apps.sellers.models import Seller


class ShippingPrefetchTests(TestCase):
  def setUp(self):
    cache.clear()
    self.fulfillment = Fulfillment.objects.create(slug="prefetch-ff", name="Prefetch FF")
    self.seller = Seller.objects.create(
      company_name="Prefetch Seller",
      fulfillment=self.fulfillment,
      wb_api_token_encrypted="token",
    )
    self.supply = Supply.objects.create(
      seller=self.seller,
      wb_supply_id="WB-SUP-PF",
      status=Supply.Status.FORMING,
    )

  @patch("apps.orders.services.supply_flow.schedule_shipping_points_prefetch")
  def test_assembly_start_prefetch_once(self, schedule_mock):
    order = Order.objects.create(
      seller=self.seller,
      wb_order_id=900001,
      barcode="111",
    )
    maybe_prefetch_shipping_points_after_assembly_progress(
      self.seller,
      order,
      on_assembly_start=True,
    )
    maybe_prefetch_shipping_points_after_assembly_progress(
      self.seller,
      order,
      on_assembly_start=True,
    )
    schedule_mock.assert_called_once()

  @patch("apps.orders.services.supply_flow.schedule_shipping_points_prefetch")
  @patch("apps.orders.services.supply_flow.count_supply_orders_pending_scan")
  @patch("apps.orders.services.supply_flow._active_forming_supplies_for_order")
  def test_near_done_prefetch_for_supply(
    self,
    supplies_mock,
    pending_mock,
    schedule_mock,
  ):
    order = Order.objects.create(
      seller=self.seller,
      wb_order_id=900002,
      barcode="222",
    )
    supplies_mock.return_value = [self.supply]
    pending_mock.return_value = SHIPPING_PREFETCH_NEAR_DONE_THRESHOLD

    maybe_prefetch_shipping_points_after_assembly_progress(self.seller, order)

    schedule_mock.assert_called_once_with(
      self.seller,
      wb_supply_id="WB-SUP-PF",
      force_refresh=True,
    )
    self.assertTrue(cache.get(_shipping_prefetch_lock_key(self.seller.id, "WB-SUP-PF")))

  @patch("apps.orders.services.supply_flow.schedule_shipping_points_prefetch")
  @patch("apps.orders.services.supply_flow.count_supply_orders_pending_scan")
  @patch("apps.orders.services.supply_flow._active_forming_supplies_for_order")
  def test_many_pending_skips_supply_prefetch(
    self,
    supplies_mock,
    pending_mock,
    schedule_mock,
  ):
    order = Order.objects.create(
      seller=self.seller,
      wb_order_id=900003,
      barcode="333",
    )
    supplies_mock.return_value = [self.supply]
    pending_mock.return_value = SHIPPING_PREFETCH_NEAR_DONE_THRESHOLD + 1

    maybe_prefetch_shipping_points_after_assembly_progress(self.seller, order)

    schedule_mock.assert_not_called()
