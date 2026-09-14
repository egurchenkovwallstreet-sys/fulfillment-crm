from datetime import datetime, timedelta

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Fulfillment
from apps.orders.models import Order, OzonPosting
from apps.sellers.models import Seller
from apps.sellers.services.crm_product_stats import (
  PERIOD_ALL,
  PERIOD_DAY,
  load_crm_product_shipment_stats,
  resolve_stats_period,
)


class CrmProductStatsTests(TestCase):
  def setUp(self):
    self.fulfillment = Fulfillment.objects.create(slug="test-ff", name="Test FF")
    self.seller = Seller.objects.create(
      company_name="Test Seller",
      fulfillment=self.fulfillment,
    )
    self.today = timezone.localdate()
    self.yesterday = self.today - timedelta(days=1)

  def test_wb_counts_only_crm_shipped_orders(self):
    Order.objects.create(
      seller=self.seller,
      wb_order_id=1001,
      barcode="111",
      status=Order.Status.NEW,
    )
    Order.objects.create(
      seller=self.seller,
      wb_order_id=1002,
      barcode="111",
      status=Order.Status.IN_DELIVERY,
      in_delivery_at=timezone.make_aware(datetime.combine(self.today, datetime.min.time())),
    )
    Order.objects.create(
      seller=self.seller,
      wb_order_id=1003,
      barcode="222",
      status=Order.Status.SHIPPED,
      in_delivery_at=timezone.make_aware(datetime.combine(self.yesterday, datetime.min.time())),
    )

    payload = load_crm_product_shipment_stats(self.seller, period=PERIOD_ALL)
    self.assertEqual(payload["total_units"], 2)
    by_barcode = {row["barcode"]: row["units"] for row in payload["items"]}
    self.assertEqual(by_barcode["111"], 1)
    self.assertEqual(by_barcode["222"], 1)

  def test_period_day_filters_by_today(self):
    Order.objects.create(
      seller=self.seller,
      wb_order_id=1004,
      barcode="111",
      status=Order.Status.SHIPPED,
      in_delivery_at=timezone.make_aware(datetime.combine(self.today, datetime.min.time())),
    )
    Order.objects.create(
      seller=self.seller,
      wb_order_id=1005,
      barcode="111",
      status=Order.Status.SHIPPED,
      in_delivery_at=timezone.make_aware(datetime.combine(self.yesterday, datetime.min.time())),
    )

    payload = load_crm_product_shipment_stats(self.seller, period=PERIOD_DAY)
    self.assertEqual(payload["total_units"], 1)

  def test_ozon_counts_quantity(self):
    OzonPosting.objects.create(
      seller=self.seller,
      posting_number="OZ-1",
      ozon_status="awaiting_deliver",
      barcode="OZ-111",
      quantity=3,
      shipped_at=timezone.now(),
    )
    payload = load_crm_product_shipment_stats(self.seller, marketplace="ozon", period=PERIOD_ALL)
    self.assertEqual(payload["total_units"], 3)

  def test_barcode_search(self):
    Order.objects.create(
      seller=self.seller,
      wb_order_id=1006,
      barcode="4601234567890",
      status=Order.Status.SHIPPED,
      in_delivery_at=timezone.now(),
    )
    Order.objects.create(
      seller=self.seller,
      wb_order_id=1007,
      barcode="999",
      status=Order.Status.SHIPPED,
      in_delivery_at=timezone.now(),
    )
    payload = load_crm_product_shipment_stats(
      self.seller,
      period=PERIOD_ALL,
      barcode="460123",
    )
    self.assertEqual(payload["total_units"], 1)
    self.assertEqual(payload["items"][0]["barcode"], "4601234567890")

  def test_resolve_custom_period_swaps_dates(self):
    start, end, preset = resolve_stats_period(
      period="custom",
      date_from=self.today,
      date_to=self.yesterday,
    )
    self.assertEqual(preset, "custom")
    self.assertEqual(start, self.yesterday)
    self.assertEqual(end, self.today)
