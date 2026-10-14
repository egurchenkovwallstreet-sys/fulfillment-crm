from unittest.mock import patch

from django.test import TestCase

from apps.accounts.models import Fulfillment, User
from apps.orders.models import Order
from apps.orders.services.marking_verification import verify_marking_orders
from apps.sellers.models import Seller
from apps.warehouse.models import Cell, Product


class VerifyMarkingEmptyMetaTest(TestCase):
  def setUp(self):
    self.fulfillment = Fulfillment.objects.create(slug="ff-vmeta", name="FF")
    self.user = User.objects.create_user(
      username="manager-vmeta",
      password="pass",
      role=User.Role.MANAGER,
      fulfillment=self.fulfillment,
    )
    self.seller = Seller.objects.create(
      company_name="Verify Meta",
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
      wb_order_id=900201,
      barcode="4600000000001",
      product=self.product,
      status=Order.Status.LABEL_PRINTED,
      wb_supplier_status="confirm",
      has_sticker=True,
      marking_code="0104600000000010215ABC1234567890",
      marking_verify_status="pending",
    )

  @patch("apps.integrations.tasks.bind_order_marking_wb_task.apply_async")
  @patch(
    "apps.orders.services.marking_verification.push_marking_to_wb_orders",
    return_value={"sent_count": 0, "error_count": 0, "verify_results": []},
  )
  @patch(
    "apps.orders.services.marking_verification.sync_orders_marking_from_wb",
    return_value=([], 0),
  )
  def test_empty_wb_meta_returns_pending_not_exception(self, _sync, _push, mock_bind):
    results = verify_marking_orders(
      self.seller,
      [self.order.id],
      user=self.user,
      force_recheck=False,
      batch=False,
    )
    self.assertEqual(results, [])
    mock_bind.assert_called_once()
