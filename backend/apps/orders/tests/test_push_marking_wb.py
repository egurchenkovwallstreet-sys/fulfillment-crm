from unittest.mock import patch

from django.test import TestCase

from apps.accounts.models import Fulfillment, User
from apps.orders.models import Order
from apps.orders.services.marking_verification import push_marking_to_wb_orders
from apps.sellers.models import Seller
from apps.warehouse.models import Cell, Product


class PushMarkingWbTest(TestCase):
  def setUp(self):
    self.fulfillment = Fulfillment.objects.create(slug="ff-push", name="FF")
    self.user = User.objects.create_user(
      username="manager-push",
      password="pass",
      role=User.Role.MANAGER,
      fulfillment=self.fulfillment,
    )
    self.seller = Seller.objects.create(
      company_name="Push Test",
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
    self.code = "0104600000000010215ABC1234567890"
    self.order = Order.objects.create(
      seller=self.seller,
      wb_order_id=900101,
      barcode="4600000000001",
      product=self.product,
      status=Order.Status.LABEL_PRINTED,
      wb_supplier_status="confirm",
      has_sticker=True,
      marking_code=self.code,
      marking_verify_status="pending",
    )

  @patch("apps.integrations.tasks.verify_seller_marking_codes.apply_async")
  @patch("apps.orders.services.assembly._push_marking_code_to_wb")
  def test_push_sends_each_code_to_matching_wb_order(self, mock_push, mock_verify):
    result = push_marking_to_wb_orders(self.seller, user=self.user)

    self.assertEqual(result["sent_count"], 1)
    self.assertEqual(result["error_count"], 0)
    mock_push.assert_called_once_with(self.order, self.code, user=self.user)
    mock_verify.assert_called_once()

  @patch("apps.integrations.tasks.verify_seller_marking_codes.apply_async")
  @patch("apps.orders.services.assembly._push_marking_code_to_wb")
  def test_push_skips_unrequested_orders(self, mock_push, mock_verify):
    other = Order.objects.create(
      seller=self.seller,
      wb_order_id=900102,
      barcode="4600000000001",
      product=self.product,
      status=Order.Status.LABEL_PRINTED,
      wb_supplier_status="confirm",
      has_sticker=True,
      marking_code="0104600000000010215OTHERCODE000000",
      marking_verify_status="pending",
    )

    result = push_marking_to_wb_orders(self.seller, [self.order.id], user=self.user)

    self.assertEqual(result["sent_count"], 1)
    mock_push.assert_called_once_with(self.order, self.code, user=self.user)
    self.assertNotEqual(mock_push.call_args[0][0].id, other.id)
