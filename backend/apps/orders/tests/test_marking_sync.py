from django.test import SimpleTestCase, TestCase

from apps.accounts.models import Fulfillment
from apps.orders.models import Order
from apps.orders.services.marking import parse_marking_verify_decision
from apps.orders.services.marking_verification import (
  VERIFY_PENDING,
  VERIFY_VERIFIED,
  _meta_marking_decision,
  _extract_sgtin_decision,
  _resolve_marking_decision,
  order_marking_ready,
)
from apps.sellers.models import Seller
from apps.warehouse.models import Cell, Product


class ResolveMarkingDecisionTests(SimpleTestCase):
  def test_crm_code_without_wb_meta_is_pending(self):
    decision = _resolve_marking_decision(None, has_code=True, treat_missing_as_required=False)
    self.assertEqual(decision, VERIFY_PENDING)

  def test_crm_code_with_filled_meta_is_verified(self):
    meta = {
      "id": 1,
      "metaDetails": [{"key": "sgtin", "value": "010", "decision": "filled"}],
    }
    decision = _resolve_marking_decision(meta, has_code=True, treat_missing_as_required=False)
    self.assertEqual(parse_marking_verify_decision(decision)[0], VERIFY_VERIFIED)

  def test_no_code_no_meta_not_required(self):
    decision = _resolve_marking_decision(None, has_code=False, treat_missing_as_required=False)
    self.assertEqual(decision, "")


class OrderMarkingReadyTests(TestCase):
  def setUp(self):
    self.fulfillment = Fulfillment.objects.create(slug="ff-ready", name="FF")
    self.seller = Seller.objects.create(
      company_name="Test",
      fulfillment=self.fulfillment,
      wb_enabled=True,
    )
    self.cell = Cell.objects.create(seller=self.seller, number="B1", marketplace="wb")
    self.product = Product.objects.create(
      seller=self.seller,
      barcode="4600000000002",
      cell=self.cell,
      requires_marking=True,
    )

  def test_pending_code_not_ready_for_delivery(self):
    order = Order.objects.create(
      seller=self.seller,
      wb_order_id=800001,
      barcode="4600000000002",
      product=self.product,
      marking_code="0104600000000010215ABC",
      marking_verify_status="pending",
      marking_bound=False,
    )
    self.assertFalse(order_marking_ready(order))

  def test_verified_and_bound_is_ready(self):
    order = Order.objects.create(
      seller=self.seller,
      wb_order_id=800002,
      barcode="4600000000002",
      product=self.product,
      marking_code="0104600000000010215ABC",
      marking_verify_status="verified",
      marking_bound=True,
    )
    self.assertTrue(order_marking_ready(order))


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
