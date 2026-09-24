from django.test import TestCase

from apps.accounts.models import Fulfillment, User
from apps.orders.models import Order
from apps.orders.services.assembly import (
  AssemblyError,
  _match_order_by_scan,
  scan_order_barcode,
)
from apps.sellers.models import Seller
from apps.warehouse.models import Cell, Product, ProductBarcodeAlias


class AssemblyBarcodeMatchTest(TestCase):
  def setUp(self):
    self.fulfillment = Fulfillment.objects.create(slug="ff-barcode", name="FF")
    self.user = User.objects.create_user(
      username="mgr-barcode",
      password="pass",
      role=User.Role.MANAGER,
      fulfillment=self.fulfillment,
    )
    self.seller = Seller.objects.create(
      company_name="Barcode Test",
      fulfillment=self.fulfillment,
      wb_enabled=True,
      wb_api_token_encrypted="enc",
    )
    self.cell = Cell.objects.create(seller=self.seller, number="A1", marketplace="wb")

    self.product_50 = Product.objects.create(
      seller=self.seller,
      barcode="04660727916563",
      cell=self.cell,
    )
    ProductBarcodeAlias.objects.create(
      product=self.product_50,
      barcode="04628529294012",
    )

    self.product_48 = Product.objects.create(
      seller=self.seller,
      barcode="04628529294029",
      cell=self.cell,
    )
    ProductBarcodeAlias.objects.create(
      product=self.product_48,
      barcode="04628529294030",
    )

    self.order_50 = Order.objects.create(
      seller=self.seller,
      wb_order_id=500001,
      barcode="04660727916563",
      product=self.product_50,
      status=Order.Status.IN_PICKING,
      wb_supplier_status="confirm",
      has_sticker=True,
      sticker_file="c3RpY2tlcg==",
    )
    self.order_48 = Order.objects.create(
      seller=self.seller,
      wb_order_id=480001,
      barcode="04628529294029",
      product=self.product_48,
      status=Order.Status.IN_PICKING,
      wb_supplier_status="confirm",
      has_sticker=True,
      sticker_file="b3RoZXI=",
    )

  def _scannable_qs(self):
    from apps.orders.services.assembly import _scannable_orders_qs

    return _scannable_orders_qs(self.seller)

  def test_exact_barcode_matches_correct_order(self):
    matched = _match_order_by_scan(self._scannable_qs(), "04660727916563", seller=self.seller)
    self.assertEqual(matched.id, self.order_50.id)

  def test_second_barcode_matches_same_sku_order(self):
    matched = _match_order_by_scan(self._scannable_qs(), "04628529294012", seller=self.seller)
    self.assertEqual(matched.id, self.order_50.id)

  def test_scan_other_size_does_not_match_wrong_order(self):
    matched = _match_order_by_scan(self._scannable_qs(), "04628529294029", seller=self.seller)
    self.assertEqual(matched.id, self.order_48.id)
    self.assertNotEqual(matched.id, self.order_50.id)

  def test_unknown_barcode_rejected(self):
    with self.assertRaises(AssemblyError) as ctx:
      scan_order_barcode(self.seller, "9999999999999", user=self.user)
    self.assertIn(ctx.exception.code, ("not_in_pick_list", "order_not_found"))

  def test_intake_barcode_finds_order_with_wb_second_barcode(self):
    """Приёмка по A, заказ WB пришёл на B — после sync оба в одной паре SKU."""
    from apps.orders.models import PickList, PickListItem
    from apps.orders.services.assembly import _scan_allowed_in_pick_list
    from apps.warehouse.services.product_lookup import sync_product_wb_barcodes

    product = Product.objects.create(
      seller=self.seller,
      barcode="04660727916563",
      cell=self.cell,
      wb_chrt_id=77001,
    )
    order = Order.objects.create(
      seller=self.seller,
      wb_order_id=500099,
      barcode="04628529294012",
      product=product,
      wb_warehouse_id=100,
      status=Order.Status.IN_PICKING,
      wb_supplier_status="confirm",
      has_sticker=True,
      sticker_file="c3RpY2tlcg==",
    )
    pick_list = PickList.objects.create(
      seller=self.seller,
      marketplace="wb",
      wb_warehouse_id=100,
      warehouse_name="Склад",
    )
    PickListItem.objects.create(
      pick_list=pick_list,
      cell=self.cell,
      product=product,
      barcode=product.barcode,
      quantity=1,
    )

    sync_product_wb_barcodes(
      self.seller,
      product,
      extra_barcodes={order.barcode},
    )

    self.assertTrue(_scan_allowed_in_pick_list(pick_list, "04660727916563"))
    matched = _match_order_by_scan(
      Order.objects.filter(pk=order.pk),
      "04660727916563",
      seller=self.seller,
    )
    self.assertEqual(matched.id, order.id)

  def test_repeat_chz_scan_returns_marking_already_bound(self):
    self.order_50.status = Order.Status.LABEL_PRINTED
    self.order_50.marking_code = "0104600000000010215ABC1234567890"
    self.order_50.save(
      update_fields=["status", "marking_code", "updated_at"],
    )
    with self.assertRaises(AssemblyError) as ctx:
      scan_order_barcode(
        self.seller,
        "0104600000000010215ABC1234567890",
        user=self.user,
      )
    self.assertEqual(ctx.exception.code, "marking_already_bound")
    self.assertEqual(ctx.exception.order.id, self.order_50.id)

  def test_same_barcode_picks_next_order_after_first_printed(self):
    """8 заказов одного баркода — после печати первого следующий скан берёт следующий заказ."""
    from apps.orders.models import PickList, PickListItem

    barcode = "04660727916563"
    pick_list = PickList.objects.create(
      seller=self.seller,
      marketplace="wb",
      wb_warehouse_id=100,
      warehouse_name="Склад",
    )
    PickListItem.objects.create(
      pick_list=pick_list,
      cell=self.cell,
      product=self.product_50,
      barcode=barcode,
      quantity=3,
    )

    self.order_50.sticker_part_a = "111"
    self.order_50.sticker_part_b = "222"
    self.order_50.status = Order.Status.LABEL_PRINTED
    self.order_50.save(
      update_fields=["sticker_part_a", "sticker_part_b", "status", "updated_at"],
    )

    second = Order.objects.create(
      seller=self.seller,
      wb_order_id=500002,
      barcode=barcode,
      product=self.product_50,
      status=Order.Status.ASSEMBLED,
      wb_supplier_status="confirm",
      has_sticker=True,
      sticker_file="c3RpY2tlcjI=",
      sticker_part_a="333",
      sticker_part_b="444",
    )
    third = Order.objects.create(
      seller=self.seller,
      wb_order_id=500003,
      barcode=barcode,
      product=self.product_50,
      status=Order.Status.IN_PICKING,
      wb_supplier_status="confirm",
      has_sticker=True,
      sticker_file="c3RpY2tlcjM=",
      sticker_part_a="555",
      sticker_part_b="666",
    )

    matched = _match_order_by_scan(self._scannable_qs(), barcode, seller=self.seller)
    self.assertEqual(matched.id, second.id)

    result = scan_order_barcode(self.seller, barcode, user=self.user)
    self.assertEqual(result["order"].id, second.id)
    self.assertNotEqual(result["order"].id, self.order_50.id)
    self.assertNotEqual(result["order"].id, third.id)
