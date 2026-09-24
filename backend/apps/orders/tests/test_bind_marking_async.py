from unittest.mock import patch

from django.test import TestCase

from apps.accounts.models import Fulfillment, User
from apps.orders.models import Order
from apps.orders.services.assembly import AssemblyError, bind_marking_and_print
from apps.sellers.models import Seller
from apps.warehouse.models import Cell, Product


class BindMarkingStrictPrintTest(TestCase):
  def setUp(self):
    self.fulfillment = Fulfillment.objects.create(slug="ff-mark", name="FF")
    self.user = User.objects.create_user(
      username="manager",
      password="pass",
      role=User.Role.MANAGER,
      fulfillment=self.fulfillment,
    )
    self.seller = Seller.objects.create(
      company_name="Test",
      fulfillment=self.fulfillment,
      wb_enabled=True,
      wb_api_token_encrypted="enc",
    )
    self.cell = Cell.objects.create(seller=self.seller, number="A1", marketplace="wb")
    self.product = Product.objects.create(
      seller=self.seller,
      barcode="4600000000001",
      cell=self.cell,
      requires_marking=True,
    )
    self.order = Order.objects.create(
      seller=self.seller,
      wb_order_id=900001,
      barcode="4600000000001",
      product=self.product,
      status=Order.Status.ASSEMBLED,
      wb_supplier_status="confirm",
      has_sticker=True,
      sticker_file="aGVsbG8=",
    )

  @patch("apps.integrations.tasks.record_sticker_billing_task.delay")
  @patch("apps.integrations.tasks.bind_order_marking_wb_task.delay")
  @patch("apps.integrations.tasks.verify_seller_marking_codes.apply_async")
  @patch(
    "apps.warehouse.services.stock_deduction.deduct_stock_for_sticker_print",
    return_value={"deducted": True},
  )
  def test_bind_marking_print_first_wb_in_background(
    self, _stock, mock_verify, mock_bind_delay, mock_billing_delay,
  ):
    code = "0104600000000010215ABC1234567890"
    with self.captureOnCommitCallbacks(execute=True):
      result = bind_marking_and_print(
        self.seller,
        self.order.id,
        code,
        user=self.user,
      )

    self.assertEqual(result["action"], "print")
    self.assertFalse(result["immediate_verify"])
    mock_bind_delay.assert_called_once_with(self.order.id, code, self.user.id)
    mock_billing_delay.assert_called_once_with(self.order.id)
    mock_verify.assert_not_called()

    self.order.refresh_from_db()
    self.assertEqual(self.order.status, Order.Status.LABEL_PRINTED)
    self.assertEqual(self.order.marking_code, code)
    self.assertEqual(self.order.marking_verify_status, "pending")
    self.assertFalse(self.order.marking_bound)

  @patch("apps.integrations.tasks.record_sticker_billing_task.delay")
  @patch("apps.integrations.tasks.bind_order_marking_wb_task.delay")
  @patch("apps.integrations.tasks.verify_seller_marking_codes.apply_async")
  @patch(
    "apps.warehouse.services.stock_deduction.deduct_stock_for_sticker_print",
    return_value={"deducted": True},
  )
  def test_bind_marking_rejects_cyrillic_before_wb(
    self, _stock, _verify, mock_bind_delay, mock_billing_delay,
  ):
    with self.assertRaises(AssemblyError) as ctx:
      bind_marking_and_print(
        self.seller,
        self.order.id,
        "абв0104600000000010215",
        user=self.user,
      )
    self.assertEqual(ctx.exception.code, "invalid_marking_code")
    mock_bind_delay.assert_not_called()
    mock_billing_delay.assert_not_called()
