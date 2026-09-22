from django.test import TestCase

from apps.accounts.models import Fulfillment
from apps.integrations.marketplace import WB
from apps.orders.models import Order, PickList, PickListItem
from apps.orders.serializers import PickListSerializer
from apps.orders.services.pick_list import _cell_sort_key, _group_orders_for_pick_list
from apps.sellers.models import Seller
from apps.warehouse.models import Cell, Product


class PickListCellOrderTests(TestCase):
  def setUp(self):
    self.fulfillment = Fulfillment.objects.create(slug="test-ff-cells", name="Test FF")
    self.seller = Seller.objects.create(
      company_name="Test Seller",
      fulfillment=self.fulfillment,
    )

  def test_cell_sort_key_numeric_order(self):
    keys = [_cell_sort_key(str(n)) for n in (1, 10, 2, 3)]
    self.assertEqual(sorted(keys), keys)

  def test_cell_sort_key_without_cell_goes_last(self):
    self.assertGreater(_cell_sort_key("—"), _cell_sort_key("99"))

  def test_group_orders_sorted_by_cell_number(self):
    cells = [
      Cell.objects.create(seller=self.seller, number=str(n), is_occupied=True, marketplace=WB)
      for n in (12, 3, 25, 7)
    ]
    products = [
      Product.objects.create(
        seller=self.seller,
        cell=cell,
        barcode=f"bc-{cell.number}",
        marketplace=WB,
        quantity=1,
      )
      for cell in cells
    ]
    orders = [
      Order.objects.create(
        seller=self.seller,
        wb_order_id=1000 + index,
        product=product,
        barcode=product.barcode,
        wb_warehouse_id=123,
      )
      for index, product in enumerate(products)
    ]

    items, _skipped = _group_orders_for_pick_list(self.seller, orders)

    self.assertEqual([item["cell_number"] for item in items], ["3", "7", "12", "25"])

  def test_pick_list_serializer_returns_items_in_cell_order(self):
    pick_list = PickList.objects.create(
      seller=self.seller,
      marketplace=WB,
      wb_warehouse_id=12345,
      warehouse_name="Склад 1",
    )
    cells = [
      Cell.objects.create(seller=self.seller, number=str(n), is_occupied=True, marketplace=WB)
      for n in (30, 5, 11)
    ]
    products = [
      Product.objects.create(
        seller=self.seller,
        cell=cell,
        barcode=f"bc-{cell.number}",
        marketplace=WB,
        quantity=1,
      )
      for cell in cells
    ]
    for index, product in enumerate(products, start=1):
      PickListItem.objects.create(
        pick_list=pick_list,
        cell=product.cell,
        product=product,
        barcode=product.barcode,
        quantity=1,
        sort_order=index,
      )

    payload = PickListSerializer(pick_list).data
    self.assertEqual([item["cell_number"] for item in payload["items"]], ["5", "11", "30"])
