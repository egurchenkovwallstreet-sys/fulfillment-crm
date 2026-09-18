from datetime import date, timedelta
from unittest.mock import MagicMock

from django.test import SimpleTestCase
from django.utils import timezone

from apps.integrations.wb_client import WBApiError, WBClient
from apps.orders.models import Supply
from apps.orders.services.supply_flow import (
  SupplyFlowError,
  _apply_shipping_method,
  _parse_deliver_error,
  _parse_shipping_method_error,
  _prepare_wb_supply_deliver,
  _validate_shipping_date,
)


class ShippingMethodClientTests(SimpleTestCase):
  def test_set_supplies_shipping_method_requires_success_flag(self):
    client = WBClient("token")
    client._request = MagicMock(return_value={
      "results": [{
        "supplyId": "WB-GI-1",
        "success": False,
      }],
    })
    with self.assertRaises(WBApiError) as ctx:
      client.set_supplies_shipping_method([{
        "supplyId": "WB-GI-1",
        "shippingPointId": 100,
        "shippingDt": "2026-09-17",
        "shippingType": "selfShipping",
      }])
    self.assertEqual(ctx.exception.status_code, 409)

  def test_set_supplies_shipping_method_raises_on_result_error(self):
    client = WBClient("token")
    client._request = MagicMock(return_value={
      "results": [{
        "supplyId": "WB-GI-2",
        "success": False,
        "error": {"code": 409, "detail": "InvalidShippingDt"},
      }],
    })
    with self.assertRaises(WBApiError) as ctx:
      client.set_supplies_shipping_method([{
        "supplyId": "WB-GI-2",
        "shippingPointId": 100,
        "shippingDt": "2026-09-17",
        "shippingType": "selfShipping",
      }])
    self.assertIn("InvalidShippingDt", str(ctx.exception))


class DeliverErrorParserTests(SimpleTestCase):
  def test_supply_shipping_required_message(self):
    exc = WBApiError(
      "WB API ошибка 409: Specify shipping point, type and date to close the supply",
      status_code=409,
      code="SupplyShippingRequired",
    )
    text = _parse_deliver_error(exc)
    self.assertIn("параметры отгрузки", text.lower())

  def test_meta_validation_fail_lists_orders(self):
    exc = WBApiError(
      "WB API ошибка 409: Fix them to dispatch items",
      status_code=409,
      code="MetaValidationFail",
      payload={
        "code": "MetaValidationFail",
        "data": {
          "orders": [{
            "id": 123456789,
            "metaDetails": [{"key": "sgtin", "decision": "pending"}],
          }],
        },
      },
    )
    text = _parse_deliver_error(exc)
    self.assertIn("123456789", text)
    self.assertIn("маркиров", text.lower())

  def test_invalid_shipping_dt_parser(self):
    exc = WBApiError(
      "Не удалось установить параметры отгрузки WB-GI-3: InvalidShippingDt",
      status_code=409,
      code="InvalidShippingDt",
    )
    text = _parse_shipping_method_error(exc)
    self.assertIn("дату отгрузки", text.lower())


class PrepareDeliverTests(SimpleTestCase):
  def test_skips_deliver_when_wb_supply_already_closed_with_same_point(self):
    client = MagicMock()
    client.fetch_supply.return_value = {
      "done": True,
      "closedAt": "2026-09-17T10:00:00Z",
      "shippingPointId": 100,
    }
    supply = Supply(wb_supply_id="WB-GI-99", status=Supply.Status.READY)
    already = _prepare_wb_supply_deliver(
      client,
      supply,
      shipping_point_id=100,
      shipping_date=date.today(),
    )
    self.assertTrue(already)
    client.set_supplies_shipping_method.assert_not_called()

  def test_rejects_closed_supply_with_different_shipping_point(self):
    client = MagicMock()
    client.fetch_supply.return_value = {
      "done": True,
      "closedAt": "2026-09-17T10:00:00Z",
      "shippingPointId": 200,
    }
    supply = Supply(wb_supply_id="WB-GI-99", status=Supply.Status.CONFIRMED)
    with self.assertRaises(SupplyFlowError) as ctx:
      _prepare_wb_supply_deliver(
        client,
        supply,
        shipping_point_id=100,
        shipping_date=date.today(),
      )
    self.assertEqual(ctx.exception.code, "wb_shipping_locked")
    client.set_supplies_shipping_method.assert_not_called()

  def test_apply_shipping_method_runs_when_supply_confirmed(self):
    client = MagicMock()
    client.fetch_supply.return_value = {
      "shippingPointId": 100,
      "shippingDt": date.today().isoformat(),
    }
    supply = Supply(wb_supply_id="WB-GI-77", status=Supply.Status.CONFIRMED)
    _apply_shipping_method(
      client,
      supply,
      shipping_point_id=100,
      shipping_date=date.today(),
    )
    client.set_supplies_shipping_method.assert_called_once()


class ShippingDateValidationTests(SimpleTestCase):
  def test_past_date_rejected(self):
    yesterday = timezone.now().date() - timedelta(days=1)
    with self.assertRaises(Exception) as ctx:
      _validate_shipping_date(yesterday)
    self.assertEqual(getattr(ctx.exception, "code", ""), "invalid_shipping_date")
