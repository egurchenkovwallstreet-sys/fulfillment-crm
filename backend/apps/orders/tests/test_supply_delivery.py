from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Fulfillment
from apps.integrations.marketplace import WB
from apps.orders.models import Order, Supply
from apps.orders.services.supply_flow import (
  assembly_supply_orders,
  refresh_supply_readiness,
  supply_can_deliver,
  supply_can_force_deliver,
)
from apps.orders.services.wb_status import WB_STATUS_AFTER_DELIVER, WB_SUPPLIER_DELIVERY
from apps.sellers.models import Seller
from apps.warehouse.models import Cell, Product


class SupplyDeliveryDepartedOrderTests(TestCase):
  def setUp(self):
    self.fulfillment = Fulfillment.objects.create(slug="test-ff", name="Test FF")
    self.seller = Seller.objects.create(
      company_name="Test Seller",
      fulfillment=self.fulfillment,
    )
    self.cell = Cell.objects.create(seller=self.seller, number="A-1", marketplace=WB)
    self.supply = Supply.objects.create(
      seller=self.seller,
      wb_supply_id="WB-SUP-1",
      status=Supply.Status.FORMING,
    )
    self.ghost = Order.objects.create(
      seller=self.seller,
      wb_order_id=900001,
      barcode="111",
      status=Order.Status.IN_DELIVERY,
      wb_supplier_status=WB_SUPPLIER_DELIVERY,
      wb_status=WB_STATUS_AFTER_DELIVER,
      in_delivery_at=timezone.now(),
    )
    self.ready = Order.objects.create(
      seller=self.seller,
      wb_order_id=900002,
      barcode="222",
      status=Order.Status.LABEL_PRINTED,
      wb_supplier_status="confirm",
      has_sticker=True,
      sticker_part_a="A1",
      sticker_part_b="B1",
    )
    self.product = Product.objects.create(
      seller=self.seller,
      cell=self.cell,
      barcode="222",
      marketplace=WB,
      quantity=5,
    )
    self.ready.product = self.product
    self.ready.save(update_fields=["product", "updated_at"])
    self.supply.orders.add(self.ghost, self.ready)

  def test_departed_order_excluded_from_delivery_check(self):
    orders = assembly_supply_orders(self.supply, self.seller)
    self.assertEqual(len(orders), 1)
    self.assertEqual(orders[0].wb_order_id, 900002)

  def test_ready_supply_when_only_ghost_blocked(self):
    refresh_supply_readiness(self.supply, seller=self.seller)
    self.supply.refresh_from_db()
    self.assertEqual(self.supply.status, Supply.Status.READY)
    self.assertTrue(supply_can_deliver(self.supply, seller=self.seller))
    self.assertFalse(supply_can_force_deliver(self.supply, seller=self.seller))

  def test_detach_departed_order_from_active_supply(self):
    refresh_supply_readiness(self.supply, seller=self.seller)
    self.assertFalse(self.supply.orders.filter(pk=self.ghost.pk).exists())

  def test_force_deliver_flag_when_unready_order_blocks(self):
    blocker = Order.objects.create(
      seller=self.seller,
      wb_order_id=900003,
      barcode="333",
      status=Order.Status.IN_PICKING,
      wb_supplier_status="confirm",
      has_sticker=False,
    )
    self.supply.orders.add(blocker)
    refresh_supply_readiness(self.supply, seller=self.seller)
    self.assertFalse(supply_can_deliver(self.supply, seller=self.seller))
    self.assertTrue(supply_can_force_deliver(self.supply, seller=self.seller))
