from unittest.mock import patch

from django.test import TestCase

from apps.accounts.models import Fulfillment, User
from apps.sellers.models import Seller, SellerWarehouse
from apps.warehouse.models import Cell, Product
from apps.warehouse.services.intake import perform_intake
from apps.warehouse.services.wb_stocks import STOCK_MODE_INTAKE


class IntakeIncrementWbTests(TestCase):
  def setUp(self):
    self.fulfillment = Fulfillment.objects.create(slug="ff-intake", name="FF")
    self.user = User.objects.create_user(username="mgr", password="x")
    self.seller = Seller.objects.create(
      company_name="Seller",
      fulfillment=self.fulfillment,
      wb_enabled=True,
      wb_api_token_encrypted="enc",
    )
    self.warehouse = SellerWarehouse.objects.create(
      seller=self.seller,
      wb_warehouse_id=5001,
      name="WH",
      is_enabled=True,
    )
    cell = Cell.objects.create(seller=self.seller, number="1", is_occupied=True)
    self.product = Product.objects.create(
      seller=self.seller,
      barcode="4601111111111",
      cell=cell,
      quantity=10,
      wb_chrt_id=999,
    )

  @patch("apps.warehouse.services.intake_increment_wb.push_wb_stock_absolute")
  @patch("apps.warehouse.services.intake_increment_wb.fetch_wb_stock_for_barcode")
  @patch("apps.warehouse.services.intake_increment_wb.count_live_open_orders_for_barcode_on_warehouse")
  def test_intake_adds_to_live_wb_and_crm_includes_orders(
    self,
    mock_live_orders,
    mock_fetch_wb,
    mock_push,
  ):
    mock_fetch_wb.side_effect = [3, 7]
    mock_live_orders.return_value = (2, 1, 3)
    mock_push.return_value = {"ok": True}

    result = perform_intake(
      seller=self.seller,
      barcode="4601111111111",
      quantity=4,
      user=self.user,
      wb_warehouse_id=self.warehouse.id,
      stock_mode=STOCK_MODE_INTAKE,
    )

    self.product.refresh_from_db()
    self.assertEqual(result.wb_quantity_before, 3)
    self.assertEqual(result.wb_quantity_target, 7)
    self.assertEqual(result.crm_quantity_after, 10)
    self.assertEqual(self.product.quantity, 10)
    mock_push.assert_called_once()
    self.assertEqual(mock_push.call_args[0][3], 7)
