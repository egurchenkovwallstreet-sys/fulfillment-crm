from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import Fulfillment
from apps.integrations.marketplace import WB
from apps.sellers.models import Seller, SellerWarehouse
from apps.warehouse.models import Cell, Product, StockOperation
from apps.warehouse.services.fbo_assembly import (
  FboAssemblyError,
  WRONG_SELLER_MESSAGE,
  close_box,
  complete_session,
  create_box,
  create_session,
  scan_barcode,
)
from apps.warehouse.services.fbo_finalize_stocks import finalize_fbo_session_stocks

User = get_user_model()


class FboAssemblyTests(TestCase):
  def setUp(self):
    self.fulfillment = Fulfillment.objects.create(slug="fbo-ff", name="FBO FF")
    self.seller = Seller.objects.create(
      company_name="ИП FBO",
      fulfillment=self.fulfillment,
      wb_api_token_encrypted="dummy",
      wb_enabled=True,
    )
    self.warehouse = SellerWarehouse.objects.create(
      seller=self.seller,
      wb_warehouse_id=1001,
      name="FBS 1",
      is_enabled=True,
    )
    self.cell = Cell.objects.create(
      seller=self.seller,
      number="1",
      is_occupied=True,
      marketplace=WB,
    )
    self.product = Product.objects.create(
      seller=self.seller,
      cell=self.cell,
      barcode="4601111111111",
      marketplace=WB,
      quantity=70,
      wb_chrt_id=90001,
    )
    self.manager = User.objects.create_user(
      username="fbo_mgr",
      password="pass",
      role="manager",
      fulfillment=self.fulfillment,
    )
    self.client = APIClient()
    self.client.force_authenticate(user=self.manager)

  def test_scan_does_not_deduct_until_finalize(self):
    session = create_session(seller=self.seller, user=self.manager)
    box1 = create_box(session, box_number="K1")
    scan_barcode(session, box_id=box1.id, barcode="4601111111111", user=self.manager)
    scan_barcode(session, box_id=box1.id, barcode="4601111111111", user=self.manager)
    self.product.refresh_from_db()
    self.assertEqual(self.product.quantity, 70)
    close_box(session, box_id=box1.id)
    complete_session(session, user=self.manager)

  def test_wrong_seller_barcode(self):
    session = create_session(seller=self.seller, user=self.manager)
    box = create_box(session, box_number="K1")
    with self.assertRaises(FboAssemblyError) as ctx:
      scan_barcode(session, box_id=box.id, barcode="9999999999999", user=self.manager)
    self.assertEqual(str(ctx.exception), WRONG_SELLER_MESSAGE)
    self.assertEqual(ctx.exception.code, "wrong_seller")

  @patch("apps.warehouse.services.fbo_finalize_stocks.set_wb_stock_absolute")
  @patch("apps.warehouse.services.fbo_finalize_stocks.fetch_summed_wb_stocks")
  @patch("apps.warehouse.services.fbo_finalize_stocks.count_live_open_orders_for_warehouses")
  def test_finalize_stocks_formula(self, mock_reserved, mock_fetch, mock_set_wb):
    mock_reserved.return_value = (2, 3, 5)
    mock_fetch.return_value = {
      "4601111111111": {
        "total": 50,
        "by_warehouse": {self.warehouse.id: 50},
      },
    }
    mock_set_wb.return_value = 25

    session = create_session(seller=self.seller, user=self.manager)
    box = create_box(session, box_number="K1")
    for _ in range(40):
      scan_barcode(session, box_id=box.id, barcode="4601111111111", user=self.manager)
    close_box(session, box_id=box.id)
    complete_session(session, user=self.manager)

    report = finalize_fbo_session_stocks(session, user=self.manager)
    self.product.refresh_from_db()
    self.assertEqual(self.product.quantity, 30)
    line = report["lines"][0]
    self.assertEqual(line["crm_was"], 70)
    self.assertEqual(line["fbo_qty"], 40)
    self.assertEqual(line["wb_reserved_total"], 5)
    self.assertEqual(line["crm_after"], 30)
    self.assertEqual(line["wb_total_after"], 25)
    self.assertTrue(line["check_crm"])
    self.assertTrue(line["check_wb"])
    self.assertEqual(StockOperation.objects.filter(product=self.product).count(), 1)

  def test_api_create_and_scan(self):
    response = self.client.post("/api/warehouse/fbo-assembly/sessions/", {"seller_id": self.seller.id})
    self.assertEqual(response.status_code, 201)
    session_id = response.data["id"]
    response = self.client.post(
      f"/api/warehouse/fbo-assembly/sessions/{session_id}/boxes/",
      {"box_number": "BOX-A"},
    )
    self.assertEqual(response.status_code, 200)
    box_id = response.data["open_box_id"]
    response = self.client.post(
      f"/api/warehouse/fbo-assembly/sessions/{session_id}/boxes/{box_id}/scan/",
      {"barcode": "4601111111111"},
    )
    self.assertEqual(response.status_code, 200)
    self.assertEqual(response.data["last_scan"]["quantity_in_box"], 1)
