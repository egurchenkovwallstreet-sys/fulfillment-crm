from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.sellers.services.admin_billing_cache import (
  STALE_AFTER_SEC,
  billing_cache_key,
  invalidate_admin_billing_for_fulfillment,
  is_cache_stale,
  schedule_admin_billing_refresh_after_delivery,
)


class AdminBillingCacheTests(SimpleTestCase):
  def test_cache_key_scoped_by_fulfillment_and_marketplace(self):
    self.assertEqual(billing_cache_key(fulfillment_id=5, marketplace="wb"), "admin_billing_v2:ff_5:wb")
    self.assertEqual(billing_cache_key(fulfillment_id=None, marketplace="ozon"), "admin_billing_v2:all:ozon")

  def test_stale_cache_without_meta(self):
    self.assertTrue(is_cache_stale(None))
    self.assertTrue(is_cache_stale({}))

  def test_stale_threshold_is_two_hours(self):
    self.assertEqual(STALE_AFTER_SEC, 7200)


class AdminBillingCacheBehaviorTests(TestCase):
  def setUp(self):
    cache.clear()

  def test_invalidate_keeps_cached_data(self):
    key = billing_cache_key(fulfillment_id=5, marketplace="wb")
    cache.set(
      key,
      {"data": {"combined": {}}, "meta": {"cached_at": timezone.now().isoformat()}},
      3600,
    )
    with patch("apps.sellers.services.admin_billing_cache.queue_admin_billing_refresh") as queue_mock:
      invalidate_admin_billing_for_fulfillment(5)
    self.assertTrue(cache.get(key))
    self.assertEqual(queue_mock.call_count, 2)

  def test_delivery_debounce_queues_once_per_marketplace(self):
    with patch("apps.sellers.services.admin_billing_cache.queue_admin_billing_refresh") as queue_mock:
      schedule_admin_billing_refresh_after_delivery(fulfillment_id=3)
      schedule_admin_billing_refresh_after_delivery(fulfillment_id=3)
    self.assertEqual(queue_mock.call_count, 2)

  def test_fresh_cache_not_stale(self):
    meta = {"cached_at": timezone.now().isoformat()}
    self.assertFalse(is_cache_stale(meta))

  def test_old_cache_is_stale(self):
    meta = {"cached_at": (timezone.now() - timedelta(hours=3)).isoformat()}
    self.assertTrue(is_cache_stale(meta))
