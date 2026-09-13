from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import Fulfillment
from apps.warehouse.models import Cell, Product, StockOperation, XlListLine, XlListSession
from apps.warehouse.services.xl_list_intake import (
  add_line,
  build_excel_bytes,
  complete_session,
  create_session,
  scan_unit,
)

User = get_user_model()


class XlListIntakeTests(TestCase):
  def setUp(self):
    self.fulfillment = Fulfillment.objects.create(slug="test-ff", name="Test FF")
    self.user = User.objects.create_user(
      username="manager_xl_list",
      password="pass",
      role=User.Role.MANAGER,
      fulfillment=self.fulfillment,
    )

  def test_scan_and_excel_without_crm_side_effects(self):
    session = create_session(title="Test list", user=self.user)
    session, _ = scan_unit(session, "4601234567890")
    session, _ = scan_unit(session, "4601234567890")
    add_line(session, barcode="4609999999999", quantity=5)

    self.assertEqual(XlListLine.objects.filter(session=session).count(), 2)
    self.assertEqual(Product.objects.count(), 0)
    self.assertEqual(Cell.objects.count(), 0)
    self.assertEqual(StockOperation.objects.count(), 0)

    payload = build_excel_bytes(session)
    self.assertTrue(payload.startswith(b"PK"))

    session = complete_session(session, user=self.user)
    self.assertEqual(session.status, XlListSession.Status.COMPLETED)
