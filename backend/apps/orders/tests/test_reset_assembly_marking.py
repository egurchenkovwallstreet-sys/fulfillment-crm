from unittest.mock import patch

from django.test import TestCase

from apps.accounts.models import Fulfillment, User
from apps.orders.models import Order, PickList, PickListItem
from apps.orders.services.assembly import AssemblyError, reset_assembly_marking_for_pick_list
from apps.sellers.models import Seller
from apps.warehouse.models import Cell, Product


class ResetAssemblyMarkingModalTest(TestCase):
  def setUp(self):
    self.fulfillment = Fulfillment.objects.create(slug="ff-rst", name="FF")
    self.user = User.objects.create_user(
      username="mgr-rst",
      password="pass",
      role=User.Role.MANAGER,
      fulfillment=self.fulfillment,
    )
    self.seller = Seller.objects.create(
      company_name="Reset",
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
    self.pick_list = PickList.objects.create(
      seller=self.seller,
      marketplace="wb",
      wb_warehouse_id=100,
      warehouse_name="Склад",
    )
    PickListItem.objects.create(
      pick_list=self.pick_list,
      cell=self.cell,
      product=self.product,
      barcode="4600000000001",
      quantity=1,
    )
    self.order = Order.objects.create(
      seller=self.seller,
      wb_order_id=800001,
      barcode="4600000000001",
      product=self.product,
      pick_list=self.pick_list,
      status=Order.Status.LABEL_PRINTED,
      wb_supplier_status="confirm",
      marking_code="0104600000000010215ABC1234567890",
      marking_verify_status="verified",
      marking_bound=True,
      has_sticker=True,
      sticker_part_a="111",
      sticker_part_b="222",
    )

  @patch("apps.orders.services.assembly._get_client")
  def test_reset_by_modal_order_ids_without_pick_list_gate(self, mock_client):
    mock_client.return_value.delete_order_meta.return_value = None
    result = reset_assembly_marking_for_pick_list(
      self.seller,
      order_ids=[self.order.id],
      user=self.user,
    )
    self.order.refresh_from_db()
    self.assertEqual(result["reset_count"], 1)
    self.assertEqual(self.order.marking_code, "")
    self.assertEqual(self.order.status, Order.Status.ASSEMBLED)

  @patch("apps.orders.services.assembly._get_client")
  def test_reset_skips_order_without_marking_data(self, mock_client):
    fresh = Order.objects.create(
      seller=self.seller,
      wb_order_id=800002,
      barcode="4600000000001",
      product=self.product,
      pick_list=self.pick_list,
      status=Order.Status.IN_PICKING,
      wb_supplier_status="confirm",
    )
    with self.assertRaises(AssemblyError) as ctx:
      reset_assembly_marking_for_pick_list(
        self.seller,
        order_ids=[fresh.id],
        user=self.user,
      )
    self.assertEqual(ctx.exception.code, "nothing_to_reset")
    mock_client.assert_not_called()
