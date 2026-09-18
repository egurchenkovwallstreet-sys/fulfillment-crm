from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase

from apps.accounts.models import Fulfillment
from apps.orders.models import Order, Supply
from apps.orders.services.supply_flow import (
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
  def test_assembly_start_prefetches_general_and_supply_lists(self, schedule_mock):
    order = Order.objects.create(
      seller=self.seller,
      wb_order_id=900001,
      barcode="111",
    )
    self.supply.orders.add(order)

    maybe_prefetch_shipping_points_after_assembly_progress(
      self.seller,
      order,
      on_assembly_start=True,
      wb_supply_ids=["WB-SUP-PF"],
    )
    maybe_prefetch_shipping_points_after_assembly_progress(
      self.seller,
      order,
      on_assembly_start=True,
      wb_supply_ids=["WB-SUP-PF"],
    )

    self.assertGreaterEqual(schedule_mock.call_count, 2)
    schedule_mock.assert_any_call(self.seller)
    schedule_mock.assert_any_call(
      self.seller,
      wb_supply_id="WB-SUP-PF",
      force_refresh=False,
    )
    self.assertTrue(cache.get(_shipping_prefetch_lock_key(self.seller.id, "WB-SUP-PF")))

  @patch("apps.orders.services.supply_flow.schedule_shipping_points_prefetch")
  def test_scan_progress_does_not_prefetch(self, schedule_mock):
    order = Order.objects.create(
      seller=self.seller,
      wb_order_id=900002,
      barcode="222",
    )
    maybe_prefetch_shipping_points_after_assembly_progress(self.seller, order)
    schedule_mock.assert_not_called()
