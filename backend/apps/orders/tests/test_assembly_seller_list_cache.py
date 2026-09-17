from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.orders.services.assembly_seller_list import (
  _assembly_sellers_cache_key,
  get_assembly_seller_list,
)


class AssemblySellerListCacheTests(SimpleTestCase):
  def test_cache_key_scoped_by_fulfillment(self):
    user = MagicMock()
    user.fulfillment = MagicMock(id=7)
    with patch(
      "apps.orders.services.assembly_seller_list.get_user_fulfillment",
      return_value=user.fulfillment,
    ):
      key = _assembly_sellers_cache_key(user, "wb")
    self.assertEqual(key, "assembly_sellers:v1:ff7:mpwb")

  def test_refresh_bypasses_cache_read(self):
    user = MagicMock()
    cached_payload = [{"id": 1, "new": 99}]
    built_payload = [{"id": 1, "new": 3}]

    with patch(
      "apps.orders.services.assembly_seller_list.cache.get",
      return_value=cached_payload,
    ) as cache_get, patch(
      "apps.orders.services.assembly_seller_list.cache.set",
    ) as cache_set, patch(
      "apps.orders.services.assembly_seller_list.build_assembly_seller_list",
      return_value=built_payload,
    ):
      result = get_assembly_seller_list(user, "wb", refresh=True)
    cache_get.assert_not_called()
    cache_set.assert_called_once()
    self.assertEqual(result, built_payload)

  def test_serves_cached_payload_when_present(self):
    user = MagicMock()
    cached_payload = [{"id": 2, "new": 5}]
    with patch(
      "apps.orders.services.assembly_seller_list.cache.get",
      return_value=cached_payload,
    ), patch(
      "apps.orders.services.assembly_seller_list.build_assembly_seller_list",
    ) as build:
      result = get_assembly_seller_list(user, "wb", refresh=False)
    build.assert_not_called()
    self.assertEqual(result, cached_payload)
