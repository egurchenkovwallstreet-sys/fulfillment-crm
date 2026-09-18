from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Fulfillment
from apps.orders.services.assembly import get_seller_wb_tab_counts
from apps.orders.services.assembly_seller_list import build_assembly_seller_list
from apps.sellers.models import Seller


class WbTabCountsTests(TestCase):
  def setUp(self):
    self.fulfillment = Fulfillment.objects.create(slug="counts-ff", name="Counts FF")
    self.seller = Seller.objects.create(
      company_name="Counts Seller",
      fulfillment=self.fulfillment,
      wb_enabled=True,
      wb_api_token_encrypted="token",
      wb_count_new=7,
      wb_count_assembly=3,
      wb_count_delivery=2,
      wb_counts_synced_at=timezone.now(),
    )

  def test_assembly_only_uses_wb_sync_fields(self):
    counts = get_seller_wb_tab_counts(self.seller, assembly_only=True)
    self.assertEqual(counts["new"], 7)
    self.assertEqual(counts["in_picking"], 3)
    self.assertEqual(counts["in_delivery"], 2)

  def test_build_seller_list_uses_wb_sync_fields(self):
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
    self.assertEqual(payload[0]["new"], 7)
    self.assertEqual(payload[0]["in_picking"], 3)
    self.assertEqual(payload[0]["in_delivery"], 2)
