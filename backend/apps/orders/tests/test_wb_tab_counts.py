from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Fulfillment
from apps.orders.models import Order
from apps.orders.services.assembly import get_seller_wb_tab_counts
from apps.orders.services.assembly_seller_list import build_assembly_seller_list
from apps.orders.services.wb_status import WB_SUPPLIER_ASSEMBLY, WB_SUPPLIER_NEW
from apps.sellers.models import Seller, SellerWarehouse


class WbTabCountsTests(TestCase):
  def setUp(self):
    self.fulfillment = Fulfillment.objects.create(slug="counts-ff", name="Counts FF")
    self.seller = Seller.objects.create(
      company_name="Counts Seller",
      fulfillment=self.fulfillment,
      wb_enabled=True,
      wb_api_token_encrypted="token",
      wb_new_order_ids=[101, 102],
      wb_count_new=99,
      wb_count_assembly=99,
      wb_count_delivery=99,
      wb_counts_synced_at=timezone.now(),
    )
    SellerWarehouse.objects.create(
      seller=self.seller,
      wb_warehouse_id=77,
      name="WH",
      is_enabled=True,
    )
    Order.objects.create(
      seller=self.seller,
      wb_order_id=101,
      wb_warehouse_id=77,
      barcode="4601111111111",
      wb_supplier_status=WB_SUPPLIER_NEW,
      status=Order.Status.NEW,
    )
    Order.objects.create(
      seller=self.seller,
      wb_order_id=102,
      wb_warehouse_id=77,
      barcode="4602222222222",
      wb_supplier_status=WB_SUPPLIER_ASSEMBLY,
      status=Order.Status.IN_PICKING,
    )

  def test_counts_from_db_not_stale_cache_fields(self):
    counts = get_seller_wb_tab_counts(self.seller, assembly_only=True)
    self.assertEqual(counts["new"], 1)
    self.assertEqual(counts["in_picking"], 1)
    self.assertEqual(counts["in_delivery"], 0)

  def test_build_seller_list_uses_wb_lk_counts(self):
    user = type("User", (), {"fulfillment": self.fulfillment})()
    with self.settings():
      from unittest.mock import patch

      with patch(
        "apps.orders.services.assembly_seller_list.sellers_for_user",
        return_value=Seller.objects.filter(pk=self.seller.pk),
      ), patch(
        "apps.orders.services.assembly_seller_list.filter_sellers_qs",
        side_effect=lambda qs, _mp: qs,
      ):
        payload = build_assembly_seller_list(user, "wb")
    self.assertEqual(len(payload), 1)
    self.assertEqual(payload[0]["new"], 1)
    self.assertEqual(payload[0]["in_picking"], 1)
    self.assertEqual(payload[0]["in_delivery"], 0)
