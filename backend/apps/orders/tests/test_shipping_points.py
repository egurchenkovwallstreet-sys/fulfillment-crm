from django.test import SimpleTestCase

from apps.orders.services.supply_flow import (
  SC_LIST_CARGO_TYPES,
  _is_consumer_pvz_point,
  _is_ppt_shipment_point,
  _matches_vnukovo_sc,
  _matches_veshki_lipkinskoe,
  _point_supports_any_cargo,
  _split_shipping_points,
  _union_shipping_point,
)


class ShippingPointMatchersTests(SimpleTestCase):
  def test_veshki_matcher(self):
    point = {"name": "Москва (Вёшки)", "address": "Липкинское ш.", "city": "Мытищи"}
    self.assertTrue(_matches_veshki_lipkinskoe(point))

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

  def test_ppt_kept_when_not_pvz(self):
    point = {
      "name": "ППТ Москва",
      "address": "пункт приема",
      "city": "Москва",
      "officeType": "pp",
    }
    self.assertTrue(_is_ppt_shipment_point(point))

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
