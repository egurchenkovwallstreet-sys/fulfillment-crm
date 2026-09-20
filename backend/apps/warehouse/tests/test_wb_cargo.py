from django.test import SimpleTestCase, TestCase

from apps.accounts.models import Fulfillment
from apps.sellers.models import Seller, SellerWarehouse
from apps.warehouse.services.wb_cargo import (
  cargo_type_label,
  parse_wb_int,
  seller_warehouse_alternatives_text,
  warehouse_option_label,
)


class WbCargoParseTests(SimpleTestCase):
  def test_parse_wb_int(self):
    self.assertEqual(parse_wb_int("3"), 3)
    self.assertIsNone(parse_wb_int(""))
    self.assertIsNone(parse_wb_int(None))


class WbCargoHintTests(TestCase):
  def setUp(self):
    self.fulfillment = Fulfillment.objects.create(slug="cargo-ff", name="Cargo FF")
    self.seller = Seller.objects.create(
      company_name="Cargo Seller",
      fulfillment=self.fulfillment,
    )
    self.current = SellerWarehouse.objects.create(
      seller=self.seller,
      wb_warehouse_id=100,
      name="МГТ склад",
      cargo_type=1,
      delivery_type=1,
    )
    SellerWarehouse.objects.create(
      seller=self.seller,
      wb_warehouse_id=200,
      name="КГТ склад",
      cargo_type=3,
      delivery_type=1,
      is_enabled=True,
    )

  def test_warehouse_option_label(self):
    self.assertIn("МГТ", warehouse_option_label(self.current))

  def test_alternatives_text_lists_other_warehouses(self):
    text = seller_warehouse_alternatives_text(self.seller, current=self.current)
    self.assertIn("КГТ склад", text)
    self.assertIn("КГТ+", text)
