from unittest.mock import MagicMock

from django.test import SimpleTestCase

from apps.integrations.wb_client import WBApiError
from apps.orders.models import Supply
from apps.orders.services.supply_flow import (
  _append_orders_to_forming_supply,
  _supply_open_in_wb,
)


class SupplyOpenInWbTests(SimpleTestCase):
  def test_closed_supply_not_open(self):
    client = MagicMock()
    client.fetch_supply.return_value = {"done": True, "closedAt": "2026-09-17"}
    supply = Supply(wb_supply_id="WB-GI-1")
    self.assertFalse(_supply_open_in_wb(client, supply))

  def test_open_empty_supply(self):
    client = MagicMock()
    client.fetch_supply.return_value = {"done": False, "cargoType": 0}
    supply = Supply(wb_supply_id="WB-GI-2")
    self.assertTrue(_supply_open_in_wb(client, supply))


class AppendOrders409RetryTests(SimpleTestCase):
  def test_retries_with_new_supply_on_409(self):
    client = MagicMock()
    client.fetch_supply.return_value = {"done": False, "cargoType": 0}
    client.create_supply.return_value = "WB-GI-NEW"
    client.add_orders_to_supply.side_effect = [
      WBApiError("conflict", status_code=409),
      None,
    ]

    seller = MagicMock()
    seller.id = 1
    supply = Supply(wb_supply_id="WB-GI-OLD", wb_warehouse_id=10)
    supply.orders = MagicMock()
    supply.orders.values_list.return_value = []
    supply.orders.add = MagicMock()

    order = MagicMock()
    order.wb_order_id = 123
    order.sticker_file = "file.png"
    order.save = MagicMock()

    from apps.orders.services import supply_flow

    supply_flow.fetch_stickers_for_orders = MagicMock(return_value=1)
    supply_flow._create_new_forming_supply = MagicMock(
      return_value=Supply(wb_supply_id="WB-GI-NEW", wb_warehouse_id=10),
    )

    stickers, error, added, active = _append_orders_to_forming_supply(
      seller,
      supply,
      [order],
      client=client,
    )
    self.assertEqual(stickers, 1)
    self.assertEqual(error, "")
    self.assertEqual(len(added), 1)
    self.assertEqual(active.wb_supply_id, "WB-GI-NEW")
    self.assertEqual(client.add_orders_to_supply.call_count, 2)
