from django.test import SimpleTestCase

from apps.integrations.wb_client import WBApiError
from apps.orders.services.supply_flow import (
  _wb_supply_closed,
  parse_wb_supply_move_error,
)


class SupplyMoveErrorTests(SimpleTestCase):
  def test_closed_supply_message(self):
    exc = WBApiError("WB API ошибка 409: supply is closed", status_code=409, code="closed")
    text = parse_wb_supply_move_error(exc)
    self.assertIn("закрыл", text)
    self.assertIn("повторной отгрузке", text)

  def test_incorrect_parameter_message(self):
    exc = WBApiError(
      "WB API ошибка 409: Передан некорректный параметр",
      status_code=409,
      code="IncorrectParameter",
    )
    text = parse_wb_supply_move_error(exc)
    self.assertIn("некорректный параметр", text.lower())

  def test_generic_409_includes_wb_body(self):
    exc = WBApiError("WB API ошибка 409: conflict xyz", status_code=409, code="Conflict")
    text = parse_wb_supply_move_error(exc)
    self.assertIn("409", text)
    self.assertIn("conflict xyz", text)

  def test_supply_closed_by_done_and_closed_at(self):
    self.assertTrue(_wb_supply_closed({"done": True}))
    self.assertTrue(_wb_supply_closed({"done": "true"}))
    self.assertTrue(_wb_supply_closed({"closedAt": "2026-09-08T10:00:00Z"}))
    self.assertFalse(_wb_supply_closed({"done": False, "closedAt": None}))
    self.assertFalse(_wb_supply_closed({}))
