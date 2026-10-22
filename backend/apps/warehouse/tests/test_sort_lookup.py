from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import Fulfillment
from apps.integrations.marketplace import WB
from apps.sellers.models import Seller
from apps.warehouse.models import Cell, Product, ProductBarcodeAlias
from apps.warehouse.services.sort_lookup import lookup_sort_wb

User = get_user_model()


class SortLookupServiceTests(TestCase):
  def setUp(self):
    self.fulfillment = Fulfillment.objects.create(slug="sort-ff", name="Sort FF")
    self.seller = Seller.objects.create(
      company_name="ИП Тестов",
      fulfillment=self.fulfillment,
      wb_api_token_encrypted="dummy",
      wb_enabled=True,
    )
    self.cell = Cell.objects.create(
      seller=self.seller,
      number="42",
      is_occupied=True,
      marketplace=WB,
    )
    self.product = Product.objects.create(
      seller=self.seller,
      cell=self.cell,
      barcode="4601234567890",
      marketplace=WB,
      quantity=3,
    )
    self.manager = User.objects.create_user(
      username="sort_mgr",
      password="pass",
      role="manager",
      fulfillment=self.fulfillment,
    )

  def test_lookup_by_primary_barcode(self):
    result = lookup_sort_wb(self.manager, "4601234567890")
    self.assertTrue(result.found)
    self.assertEqual(result.company_name, "ИП Тестов")
    self.assertEqual(result.cell_number, "42")

  def test_lookup_by_alias_barcode(self):
    ProductBarcodeAlias.objects.create(product=self.product, barcode="4609999999999")
    result = lookup_sort_wb(self.manager, "4609999999999")
    self.assertTrue(result.found)
    self.assertEqual(result.cell_number, "42")

  def test_not_found(self):
    result = lookup_sort_wb(self.manager, "0000000000000")
    self.assertFalse(result.found)


class SortLookupApiTests(TestCase):
  def setUp(self):
    self.fulfillment = Fulfillment.objects.create(slug="sort-api", name="Sort API")
    self.seller = Seller.objects.create(
      company_name="ИП API",
      fulfillment=self.fulfillment,
      wb_api_token_encrypted="dummy",
      wb_enabled=True,
    )
    self.cell = Cell.objects.create(
      seller=self.seller,
      number="7",
      is_occupied=True,
      marketplace=WB,
    )
    Product.objects.create(
      seller=self.seller,
      cell=self.cell,
      barcode="1111111111111",
      marketplace=WB,
      quantity=1,
    )
    self.manager = User.objects.create_user(
      username="sort_api_mgr",
      password="pass",
      role="manager",
      fulfillment=self.fulfillment,
    )
    self.client = APIClient()
    self.client.force_authenticate(user=self.manager)

  def test_sort_lookup_endpoint(self):
    response = self.client.get("/api/warehouse/sort/lookup/", {"barcode": "1111111111111"})
    self.assertEqual(response.status_code, 200)
    self.assertEqual(response.data["company_name"], "ИП API")
    self.assertEqual(response.data["cell_number"], "7")
