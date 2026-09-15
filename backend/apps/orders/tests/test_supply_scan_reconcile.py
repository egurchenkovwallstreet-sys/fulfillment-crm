from datetime import datetime, timezone as dt_timezone
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Fulfillment
from apps.orders.models import Order, Supply
from apps.orders.services.supply_sync import (
  _finalize_supply_scan,
  _wb_supply_scanned_at,
  reconcile_stuck_in_delivery_supplies,
  sync_supply_scan_dates,
)
from apps.sellers.models import Seller


class WbSupplyScannedAtTests(TestCase):
  def test_scan_dt_has_priority(self):
    scanned = _wb_supply_scanned_at({
      "done": True,
      "scanDt": "2026-09-10T08:00:00Z",
      "closedAt": "2026-09-10T09:00:00Z",
    })
    self.assertEqual(
      scanned,
      datetime(2026, 9, 10, 8, 0, tzinfo=dt_timezone.utc),
    )

  def test_closed_at_without_scan_dt_is_not_warehouse_scan(self):
    self.assertIsNone(_wb_supply_scanned_at({
      "done": True,
      "closedAt": "2026-09-10T09:00:00Z",
    }))

  def test_open_supply_without_scan_is_none(self):
    self.assertIsNone(_wb_supply_scanned_at({"done": False, "closedAt": "2026-09-10T09:00:00Z"}))


class ReconcileStuckDeliveryTests(TestCase):
  def setUp(self):
    self.fulfillment = Fulfillment.objects.create(slug="test-ff", name="Test FF")
    self.seller = Seller.objects.create(
      company_name="Test Seller",
      fulfillment=self.fulfillment,
      wb_enabled=True,
      wb_api_token_encrypted="enc",
    )
    self.supply = Supply.objects.create(
      seller=self.seller,
      wb_supply_id="WB-SUP-1",
      status=Supply.Status.CONFIRMED,
    )
    self.order = Order.objects.create(
      seller=self.seller,
      wb_order_id=900001,
      barcode="4601234567890",
      status=Order.Status.IN_DELIVERY,
      in_delivery_at=timezone.now(),
    )
    self.supply.orders.add(self.order)

  def test_finalize_supply_scan_closes_order(self):
    scanned_at = timezone.now()
    closed = _finalize_supply_scan(
      self.supply,
      [self.order],
      seller=self.seller,
      scanned_at=scanned_at,
    )
    self.order.refresh_from_db()
    self.supply.refresh_from_db()
    self.assertEqual(closed, 1)
    self.assertEqual(self.order.status, Order.Status.SHIPPED)
    self.assertIsNotNone(self.supply.wb_scanned_at)

  @patch("apps.orders.services.supply_sync._get_client")
  def test_reconcile_closes_stuck_supply_from_wb_scan_dt(self, get_client_mock):
    client = MagicMock()
    client.fetch_supplies.return_value = [{
      "id": "WB-SUP-1",
      "done": True,
      "scanDt": "2026-09-10T08:00:00Z",
    }]
    get_client_mock.return_value = client

    result = reconcile_stuck_in_delivery_supplies(self.seller, client=client)

    self.order.refresh_from_db()
    self.supply.refresh_from_db()
    self.assertEqual(result["orders_closed"], 1)
    self.assertEqual(self.order.status, Order.Status.SHIPPED)
    self.assertIsNotNone(self.supply.wb_scanned_at)

  @patch("apps.orders.services.supply_sync._get_client")
  def test_sync_reopens_supply_closed_by_closed_at_only(self, get_client_mock):
    scanned_at = timezone.now()
    self.supply.wb_scanned_at = scanned_at
    self.supply.save(update_fields=["wb_scanned_at", "updated_at"])
    self.order.status = Order.Status.SHIPPED
    self.order.save(update_fields=["status", "updated_at"])

    client = MagicMock()
    client.fetch_supplies.return_value = [{
      "id": "WB-SUP-1",
      "done": True,
      "closedAt": "2026-09-10T09:00:00Z",
    }]
    client.fetch_supply.return_value = {
      "id": "WB-SUP-1",
      "done": True,
      "closedAt": "2026-09-10T09:00:00Z",
    }
    get_client_mock.return_value = client

    result = sync_supply_scan_dates(self.seller, client=client)

    self.order.refresh_from_db()
    self.supply.refresh_from_db()
    self.assertEqual(result["orders_reopened"], 1)
    self.assertEqual(self.order.status, Order.Status.IN_DELIVERY)
    self.assertIsNone(self.supply.wb_scanned_at)

  @patch("apps.orders.services.supply_sync._get_client")
  def test_sync_applies_scan_dt_from_supply_detail_when_list_omits_it(self, get_client_mock):
    client = MagicMock()
    client.fetch_supplies.return_value = [{
      "id": "WB-SUP-1",
      "done": True,
      "closedAt": "2026-09-10T09:00:00Z",
    }]
    client.fetch_supply.return_value = {
      "id": "WB-SUP-1",
      "done": True,
      "scanDt": "2026-09-10T08:00:00Z",
    }
    get_client_mock.return_value = client

    result = sync_supply_scan_dates(self.seller, client=client)

    self.order.refresh_from_db()
    self.supply.refresh_from_db()
    self.assertEqual(result["supplies_scanned"], 1)
    self.assertEqual(result["orders_closed"], 1)
    self.assertEqual(self.order.status, Order.Status.SHIPPED)
    self.assertIsNotNone(self.supply.wb_scanned_at)
    client.fetch_supply.assert_called_with("WB-SUP-1")
