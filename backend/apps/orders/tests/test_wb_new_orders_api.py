from types import SimpleNamespace

from django.test import TestCase

from apps.accounts.models import Fulfillment
from apps.orders.services.wb_status import enabled_wb_new_order_ids_from_api
from apps.sellers.models import Seller, SellerWarehouse


class WbNewOrdersFromApiTests(TestCase):
  def setUp(self):
    self.fulfillment = Fulfillment.objects.create(slug="wb-new-api", name="WB New API")
    self.seller = Seller.objects.create(
      company_name="WB New API Seller",
      fulfillment=self.fulfillment,
      wb_enabled=True,
    )
    SellerWarehouse.objects.create(
      seller=self.seller,
      wb_warehouse_id=501,
      office_id=9001,
      name="Enabled WH",
      is_enabled=True,
    )
    SellerWarehouse.objects.create(
      seller=self.seller,
      wb_warehouse_id=999,
      name="Disabled WH",
      is_enabled=False,
    )

  def test_only_enabled_warehouse_ids_from_wb_new(self):
    wb_orders = [
      SimpleNamespace(wb_order_id=1001, warehouse_id=501, office_id=None),
      SimpleNamespace(wb_order_id=1002, warehouse_id=999, office_id=None),
      SimpleNamespace(wb_order_id=1003, warehouse_id=None, office_id=9001),
    ]
    ids = enabled_wb_new_order_ids_from_api(self.seller, wb_orders)
    self.assertEqual(ids, [1001, 1003])
