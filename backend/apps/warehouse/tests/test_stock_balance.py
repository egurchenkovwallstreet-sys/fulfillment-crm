from django.test import SimpleTestCase

from apps.warehouse.services.stock_balance import compute_wb_amount_from_crm


class StockBalanceTests(SimpleTestCase):
  def test_wb_amount_subtracts_new_orders(self):
    wb_amount, restock = compute_wb_amount_from_crm(10, 3)
    self.assertEqual(wb_amount, 7)
    self.assertFalse(restock)

  def test_wb_amount_zero_when_not_enough_for_new(self):
    wb_amount, restock = compute_wb_amount_from_crm(2, 5)
    self.assertEqual(wb_amount, 0)
    self.assertTrue(restock)

  def test_wb_amount_without_new_orders(self):
    wb_amount, restock = compute_wb_amount_from_crm(8, 0)
    self.assertEqual(wb_amount, 8)
    self.assertFalse(restock)
