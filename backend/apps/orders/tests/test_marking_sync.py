from django.test import SimpleTestCase

from apps.orders.services.marking import parse_marking_verify_decision
from apps.orders.services.marking_verification import (
  _meta_marking_decision,
  _extract_sgtin_decision,
)


class MetaMarkingDecisionTests(SimpleTestCase):
  def test_invalid_format_is_error(self):
    decision = _meta_marking_decision({
      "id": 1,
      "metaDetails": [{"key": "sgtin", "decision": "sgtinInvalidFormat"}],
    })
    self.assertEqual(parse_marking_verify_decision(decision)[0], "error")

  def test_filled_then_invalid_picks_invalid(self):
    decision = _meta_marking_decision({
      "id": 1,
      "metaDetails": [
        {"key": "sgtin", "value": "010", "decision": "filled"},
        {"key": "sgtin", "decision": "sgtinNoGS"},
      ],
    })
    self.assertEqual(parse_marking_verify_decision(decision)[0], "error")

  def test_extract_sgtin_still_works(self):
    decision = _extract_sgtin_decision({
      "id": 1,
      "metaDetails": [{"key": "sgtin", "decision": "sgtinInvalidFormat"}],
    })
    self.assertEqual(parse_marking_verify_decision(decision)[0], "error")
