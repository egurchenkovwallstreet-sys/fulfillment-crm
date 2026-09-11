from django.test import SimpleTestCase

from apps.sellers.services.admin_billing_cache import billing_cache_key, is_cache_stale


class AdminBillingCacheTests(SimpleTestCase):
  def test_cache_key_scoped_by_fulfillment_and_marketplace(self):
    self.assertEqual(billing_cache_key(fulfillment_id=5, marketplace="wb"), "admin_billing_v1:ff_5:wb")
    self.assertEqual(billing_cache_key(fulfillment_id=None, marketplace="ozon"), "admin_billing_v1:all:ozon")

  def test_stale_cache_without_meta(self):
    self.assertTrue(is_cache_stale(None))
    self.assertTrue(is_cache_stale({}))
