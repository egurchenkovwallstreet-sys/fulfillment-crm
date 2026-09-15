from django.test import TestCase

from apps.accounts.models import Fulfillment
from apps.integrations.marketplace import WB
from apps.orders.models import Order, PickList, PickListItem, Supply
from apps.orders.services.assembly import _detach_order_from_pick_list
from apps.orders.services.pick_list import archived_wb_pick_lists
from apps.orders.services.supply_flow import _complete_pick_lists_after_supply_delivery
from apps.sellers.models import Seller
from apps.warehouse.models import Cell, Product


class PickListArchivePreserveItemsTests(TestCase):
  def setUp(self):
    self.fulfillment = Fulfillment.objects.create(slug="test-ff", name="Test FF")
    self.seller = Seller.objects.create(
      company_name="Test Seller",
      fulfillment=self.fulfillment,
    )
    self.cell = Cell.objects.create(seller=self.seller, number="A-1", marketplace=WB)
    self.pick_list = PickList.objects.create(
      seller=self.seller,
      marketplace=WB,
      wb_warehouse_id=12345,
      warehouse_name="Склад 1",
    )
    self.product = Product.objects.create(
      seller=self.seller,
      cell=self.cell,
      barcode="111",
      marketplace=WB,
      quantity=100,
    )
    PickListItem.objects.create(
      pick_list=self.pick_list,
      cell=self.cell,
      product=self.product,
      barcode="111",
      quantity=80,
    )
    self.orders = []
    for i in range(80):
      order = Order.objects.create(
        seller=self.seller,
        wb_order_id=100000 + i,
        barcode="111",
        product=self.product,
        pick_list=self.pick_list,
        wb_warehouse_id=12345,
        status=Order.Status.LABEL_PRINTED,
        has_sticker=True,
      )
      self.orders.append(order)
    self.supply = Supply.objects.create(
      seller=self.seller,
      wb_supply_id="WB-SUP-ARCH",
      wb_warehouse_id=12345,
      status=Supply.Status.READY,
    )
    self.supply.orders.set(self.orders)

  def test_detach_preserves_pick_list_items_for_archive(self):
    for order in self.orders:
      _detach_order_from_pick_list(order)
      order.save(update_fields=["pick_list", "updated_at"])

    _complete_pick_lists_after_supply_delivery(self.supply, seller=self.seller)

    self.pick_list.refresh_from_db()
    self.assertTrue(self.pick_list.is_completed)
    self.assertIsNotNone(self.pick_list.completed_at)
    total = sum(item.quantity for item in self.pick_list.items.all())
    self.assertEqual(total, 80)

    archived = archived_wb_pick_lists(self.seller)
    self.assertEqual(len(archived), 1)
    archived_total = sum(item.quantity for item in archived[0].items.all())
    self.assertEqual(archived_total, 80)
