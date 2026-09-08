from django.test import SimpleTestCase

from apps.integrations.wb_client import parse_orders_meta_payload
from apps.orders.services.marking import parse_marking_verify_decision
from apps.orders.services.marking_verification import _extract_sgtin_decision


class OrdersMetaPayloadTests(SimpleTestCase):
  def test_official_orders_wrapper(self):
    items = parse_orders_meta_payload({
      "orders": [
        {"id": 11, "metaDetails": [{"key": "sgtin", "value": "010", "decision": "filled"}]},
      ],
    })
    self.assertEqual(len(items), 1)
    self.assertEqual(items[0]["id"], 11)

  def test_v3_wrapper_and_id_map(self):
    items = parse_orders_meta_payload({
      "data": {
        "22": {"metaDetails": [{"key": "sgtin", "value": "010", "decision": "pending"}]},
      },
    })
    self.assertEqual(len(items), 1)
    self.assertEqual(items[0]["id"], 22)


class MarkingDecisionTests(SimpleTestCase):
  def test_filled_and_deadline_are_verified(self):
    self.assertEqual(parse_marking_verify_decision("filled")[0], "verified")
    self.assertEqual(parse_marking_verify_decision("deadlineExceeded")[0], "verified")
    self.assertEqual(parse_marking_verify_decision("optional")[0], "verified")
    self.assertEqual(parse_marking_verify_decision("pending")[0], "pending")
    self.assertEqual(parse_marking_verify_decision("sgtinNoGS")[0], "error")

  def test_string_sgtin_is_filled_not_pending(self):
    decision = _extract_sgtin_decision({"id": 1, "meta": {"sgtin": "010460095447410021"}})
    self.assertEqual(parse_marking_verify_decision(decision)[0], "verified")

  def test_value_without_decision_is_filled(self):
    decision = _extract_sgtin_decision({
      "id": 1,
      "metaDetails": [{"key": "sgtin", "value": "010460095447410021"}],
    })
    self.assertEqual(parse_marking_verify_decision(decision)[0], "verified")

  def test_filled_plus_code_string_stays_verified(self):
    decision = _extract_sgtin_decision({
      "id": 1,
      "meta": {"sgtin": "010460095447410021"},
      "metaDetails": [{"key": "sgtin", "value": "010460095447410021", "decision": "filled"}],
    })
    self.assertEqual(parse_marking_verify_decision(decision)[0], "verified")

  def test_explicit_pending_wins(self):
    decision = _extract_sgtin_decision({
      "id": 1,
      "meta": {"sgtin": "010460095447410021"},
      "metaDetails": [{"key": "sgtin", "value": "010460095447410021", "decision": "pending"}],
    })
    self.assertEqual(parse_marking_verify_decision(decision)[0], "pending")
