from django.core.cache import cache
from django.test import SimpleTestCase, TestCase

from apps.orders.services import supply_flow
from apps.orders.services.shipping_points_catalog import (
  ALL_SC_SHIPPING_CACHE_TTL,
  SC_LIST_CARGO_TYPES,
  SHIPPING_POINTS_CACHE_VERSION,
  _filter_sc_sw_points,
  _is_sc_office_type,
  _point_supports_any_cargo,
  _seller_shipping_cache_key,
  _shipping_point_zone_label,
  _union_shipping_point,
  read_cached_sc_shipping_points,
  serialize_shipping_point_for_api,
)


class ShippingPointsCatalogTests(SimpleTestCase):
  def test_sc_list_includes_mgt_and_kgt(self):
    self.assertEqual(SC_LIST_CARGO_TYPES, (1, 3))

  def test_supply_flow_reexports_cache_version(self):
    self.assertEqual(supply_flow.SHIPPING_POINTS_CACHE_VERSION, "v12")

  def test_filter_sc_sw_excludes_pp_and_pvz(self):
    points = [
      {"id": 1, "officeType": "sc"},
      {"id": 2, "officeType": "sw"},
      {"id": 3, "officeType": "pp"},
      {"id": 4, "officeType": "pvz"},
    ]
    filtered = _filter_sc_sw_points(points)
    self.assertEqual({point["id"] for point in filtered}, {1, 2})

  def test_is_sc_office_type(self):
    self.assertTrue(_is_sc_office_type({"officeType": "sc"}))
    self.assertTrue(_is_sc_office_type({"officeType": "sw"}))
    self.assertFalse(_is_sc_office_type({"officeType": "pp"}))

  def test_point_supports_any_cargo(self):
    point = {"cargoTypes": [1]}
    self.assertTrue(_point_supports_any_cargo(point, (1, 3)))
    self.assertFalse(_point_supports_any_cargo(point, (3,)))

  def test_union_shipping_point_merges_cargo_types(self):
    left = {"id": 1, "cargoTypes": [1], "name": "A"}
    right = {"id": 1, "cargoTypes": [3], "address": "addr"}
    merged = _union_shipping_point(left, right)
    self.assertEqual(merged["cargoTypes"], [1, 3])
    self.assertEqual(merged["address"], "addr")

  def test_seller_cache_key_includes_cargo(self):
    key = _seller_shipping_cache_key(42, 3)
    self.assertIn("seller:42", key)
    self.assertIn("cargo:3", key)
    self.assertIn(SHIPPING_POINTS_CACHE_VERSION, key)

  def test_seller_cache_key_includes_supply(self):
    key = _seller_shipping_cache_key(42, 1, wb_supply_id="WB-GI-99")
    self.assertIn("seller:42", key)
    self.assertIn("supply:WB-GI-99", key)

  def test_zone_label_north_for_veshki(self):
    point = {"name": "Москва (Вёшки)", "address": "Липкинское ш.", "city": "Мытищи"}
    self.assertEqual(_shipping_point_zone_label(point), "Север")

  def test_serialize_never_pins(self):
    point = {
      "id": 100,
      "name": "СЦ Внуково",
      "address": "Москва",
      "city": "Москва",
      "officeType": "sc",
      "cargoTypes": [1, 3],
    }
    payload = serialize_shipping_point_for_api(point)
    self.assertFalse(payload["is_pinned"])
    self.assertEqual(payload["id"], 100)


class ShippingPointsCacheReadTests(TestCase):
  def setUp(self):
    cache.clear()

  def test_read_cached_prefers_supply_specific_list(self):
    general_key = _seller_shipping_cache_key(7, 1)
    supply_key = _seller_shipping_cache_key(7, 1, wb_supply_id="WB-1")
    cache.set(
      general_key,
      {"sc": [{"id": 1, "name": "General", "officeType": "sc"}]},
      ALL_SC_SHIPPING_CACHE_TTL,
    )
    cache.set(
      supply_key,
      {"sc": [{"id": 99, "name": "Supply", "officeType": "sc"}]},
      ALL_SC_SHIPPING_CACHE_TTL,
    )

    points = read_cached_sc_shipping_points(7, cargo_type=1, wb_supply_id="WB-1")

    self.assertIsNotNone(points)
    self.assertEqual(points[0]["id"], 99)
