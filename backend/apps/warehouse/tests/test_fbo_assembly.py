from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import Fulfillment
from apps.integrations.marketplace import WB
from apps.sellers.models import Seller
from apps.warehouse.models import Cell, FboAssemblySession, Product, StockOperation
from apps.warehouse.services.fbo_assembly import (
  FboAssemblyError,
  WRONG_SELLER_MESSAGE,
  close_box,
  create_box,
  create_session,
  scan_barcode,
)

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
    self.other = Seller.objects.create(
      company_name="ИП Другой",
      fulfillment=self.fulfillment,
      wb_api_token_encrypted="dummy",
      wb_enabled=True,
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
      quantity=2,
    )
    self.manager = User.objects.create_user(
      username="fbo_mgr",
      password="pass",
      role="manager",
      fulfillment=self.fulfillment,
    )
    self.client = APIClient()
    self.client.force_authenticate(user=self.manager)

  def test_scan_deducts_and_same_barcode_in_two_boxes(self):
    session = create_session(seller=self.seller, user=self.manager)
    box1 = create_box(session, box_number="K1")
    scan_barcode(session, box_id=box1.id, barcode="4601111111111", user=self.manager)
    scan_barcode(session, box_id=box1.id, barcode="4601111111111", user=self.manager)
    close_box(session, box_id=box1.id)
    self.product.refresh_from_db()
    self.assertEqual(self.product.quantity, 0)

    box2 = create_box(session, box_number="K2")
    scan_barcode(session, box_id=box2.id, barcode="4601111111111", user=self.manager)
    self.product.refresh_from_db()
    self.assertEqual(self.product.quantity, 0)

    line1 = box1.lines.get(barcode="4601111111111")
    line2 = box2.lines.get(barcode="4601111111111")
    self.assertEqual(line1.quantity, 2)
    self.assertEqual(line2.quantity, 1)
    self.assertNotEqual(line1.pk, line2.pk)

  def test_scan_zero_stock_does_not_go_negative(self):
    self.product.quantity = 0
    self.product.save(update_fields=["quantity"])
    session = create_session(seller=self.seller, user=self.manager)
    box = create_box(session, box_number="K0")
    _, deducted = scan_barcode(session, box_id=box.id, barcode="4601111111111", user=self.manager)
    self.product.refresh_from_db()
    self.assertFalse(deducted)
    self.assertEqual(self.product.quantity, 0)
    self.assertEqual(box.lines.get().quantity, 1)
    self.assertEqual(
      StockOperation.objects.filter(product=self.product).count(),
      0,
    )

  def test_wrong_seller_barcode(self):
    session = create_session(seller=self.seller, user=self.manager)
    box = create_box(session, box_number="K1")
    with self.assertRaises(FboAssemblyError) as ctx:
      scan_barcode(session, box_id=box.id, barcode="9999999999999", user=self.manager)
    self.assertEqual(str(ctx.exception), WRONG_SELLER_MESSAGE)
    self.assertEqual(ctx.exception.code, "wrong_seller")

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
    self.assertTrue(response.data["last_scan"]["stock_deducted"])
