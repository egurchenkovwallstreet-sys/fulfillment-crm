from django.test import SimpleTestCase

from apps.orders.services.supply_flow import (
  SC_LIST_CARGO_TYPES,
  SHIPPING_POINTS_CACHE_VERSION,
  _seller_shipping_cache_key,
  _is_consumer_pvz_point,
  _is_explicit_ppt_point,
  _is_ppt_shipment_point,
  _matches_vnukovo_sc,
  _matches_veshki_lipkinskoe,
  _merge_pinned_shipping_points,
  _pick_best_matching_point,
  _point_supports_any_cargo,
  _shipping_point_zone_label,
  _split_shipping_points,
  _union_shipping_point,
  _veshki_lipkinskoe_score,
  _vnukovo_sc_score,
)


class ShippingPointMatchersTests(SimpleTestCase):
  def test_veshki_matcher_requires_lipkinskoe(self):
    point = {"name": "Москва (Вёшки)", "address": "Липкинское ш., 2-й км", "city": "Мытищи"}
    self.assertTrue(_matches_veshki_lipkinskoe(point))

  def test_loose_vesh_name_without_lipkinskoe_rejected(self):
    point = {"name": "СЦ Москва Запад", "address": "Москва, Вешковский пер.", "city": "Москва"}
    self.assertFalse(_matches_veshki_lipkinskoe(point))

  def test_pick_best_veshki_point(self):
    points = [
      {"id": 1, "name": "СЦ Коледино", "address": "Софьино", "city": "Московская область"},
      {"id": 2, "name": "Москва (Вёшки)", "address": "Липкинское ш., 2-й км", "city": "Мытищи"},
    ]
    best = _pick_best_matching_point(
      points,
      _matches_veshki_lipkinskoe,
      scorer=_veshki_lipkinskoe_score,
    )
    self.assertEqual(best["id"], 2)

  def test_vnukovo_matcher(self):
    point = {"name": "СЦ Внуково", "address": "Москва", "city": "Москва"}
    self.assertTrue(_matches_vnukovo_sc(point))

  def test_pvz_excluded_from_ppt(self):
    point = {
      "name": "ПВЗ Wildberries",
      "address": "пункт выдачи заказов",
      "city": "Москва",
      "officeType": "pp",
    }
    self.assertTrue(_is_consumer_pvz_point(point))
    self.assertFalse(_is_ppt_shipment_point(point))

  def test_ppt_kept_when_explicit_markers(self):
    point = {
      "name": "ППТ Москва",
      "address": "пункт приема",
      "city": "Москва",
      "officeType": "pp",
    }
    self.assertTrue(_is_explicit_ppt_point(point))
    self.assertTrue(_is_ppt_shipment_point(point))

  def test_ambiguous_pp_without_markers_excluded(self):
    point = {
      "name": "Wildberries",
      "address": "Москва, ул. Пример",
      "city": "Москва",
      "officeType": "pp",
    }
    self.assertFalse(_is_ppt_shipment_point(point))

  def test_sc_list_includes_mgt_and_kgt(self):
    self.assertEqual(SC_LIST_CARGO_TYPES, (1, 3))

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

  def test_merge_pinned_does_not_replace_veshki_ids(self):
    veshki_sc = {
      "id": 100,
      "name": "Москва (Вёшки)",
      "address": "Липкинское ш., 2-й км",
      "city": "Мытищи",
      "officeType": "sc",
    }
    veshki_sw = {
      "id": 101,
      "name": "Склад Вёшки",
      "address": "Липкинское ш., 2-й км",
      "city": "Мытищи",
      "officeType": "sw",
    }

    class DummyClient:
      def fetch_shipping_points(self, city, cargo_type):
        return [veshki_sw]

    merged = _merge_pinned_shipping_points(
      DummyClient(),
      1,
      [veshki_sc, veshki_sw],
    )
    ids = {int(point["id"]) for point in merged}
    self.assertEqual(ids, {100, 101})

  def test_vnukovo_zone_label(self):
    point = {"name": "СЦ Внуково", "address": "Москва", "city": "Москва"}
    self.assertEqual(_shipping_point_zone_label(point), "Запад/Юг")

  def test_veshki_zone_label(self):
    point = {"name": "Москва (Вёшки)", "address": "Липкинское ш., 2-й км", "city": "Мытищи"}
    self.assertEqual(_shipping_point_zone_label(point), "Север")

  def test_vnukovo_score_prefers_vnukovo_name(self):
    points = [
      {"id": 1, "name": "СЦ Рассказовка", "address": "Рассказовка", "city": "Москва"},
      {"id": 2, "name": "СЦ Внуково", "address": "Внуково", "city": "Москва"},
    ]
    best = _pick_best_matching_point(points, _matches_vnukovo_sc, scorer=_vnukovo_sc_score)
    self.assertEqual(best["id"], 2)

  def test_split_sc_and_ppt(self):
    points = [
      {"id": 1, "officeType": "sc", "name": "СЦ", "city": "", "address": ""},
      {"id": 2, "officeType": "sw", "name": "Склад", "city": "", "address": ""},
      {
        "id": 3,
        "officeType": "pp",
        "name": "ППТ",
        "city": "",
        "address": "пункт приема",
      },
      {
        "id": 4,
        "officeType": "pp",
        "name": "ПВЗ",
        "city": "",
        "address": "пункт выдачи",
      },
    ]
    sc_points, pp_points = _split_shipping_points(points)
    self.assertEqual({point["id"] for point in sc_points}, {1, 2})
    self.assertEqual([point["id"] for point in pp_points], [3])
