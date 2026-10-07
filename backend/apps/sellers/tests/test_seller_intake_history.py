from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import Fulfillment
from apps.integrations.marketplace import WB
from apps.integrations.models import AuditLog
from apps.sellers.models import Seller
from apps.sellers.services.seller_intake_history import (
  get_seller_intake_receipt_detail,
  list_seller_intake_receipts,
)
from apps.warehouse.services.wb_stocks import STOCK_MODE_INTAKE

User = get_user_model()


class SellerIntakeHistoryTests(TestCase):
  def setUp(self):
    self.fulfillment = Fulfillment.objects.create(slug="ff-int-h", name="FF")
    self.seller = Seller.objects.create(
      company_name="Seller Intake",
      fulfillment=self.fulfillment,
    )
    self.user = User.objects.create_user(username="seller1", password="x", role="seller", seller=self.seller)
    self.log = AuditLog.objects.create(
      user=self.user,
      seller=self.seller,
      action_type=AuditLog.ActionType.INTAKE,
      message="Приёмка 5 шт., баркод 123",
      details={
        "barcode": "1234567890123",
        "quantity": 5,
        "stock_mode": STOCK_MODE_INTAKE,
        "marketplace": WB,
      },
    )

  def test_list_and_detail_manual(self):
    receipts = list_seller_intake_receipts(self.seller, marketplace=WB)
    self.assertEqual(len(receipts), 1)
    detail = get_seller_intake_receipt_detail(
      self.seller,
      receipts[0]["id"],
      marketplace=WB,
    )
    self.assertEqual(len(detail["items"]), 1)
    self.assertEqual(detail["items"][0]["quantity"], 5)
    self.assertEqual(detail["items"][0]["barcode"], "1234567890123")
