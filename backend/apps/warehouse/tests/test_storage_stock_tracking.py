from datetime import date
from decimal import Decimal
from unittest.mock import Mock

from django.test import SimpleTestCase

from apps.warehouse.models import StockOperation
from apps.warehouse.services.storage_stock_tracking import apply_stock_operation_balance


class StorageStockTrackingTests(SimpleTestCase):
  def _op(self, op_type: str, quantity: int, comment: str = "") -> Mock:
    operation = Mock()
    operation.operation_type = op_type
    operation.quantity = quantity
    operation.comment = comment
    return operation

  def test_intake_adds_quantity(self):
    balance = apply_stock_operation_balance(
      5,
      self._op(StockOperation.OperationType.INTAKE, 3),
    )
    self.assertEqual(balance, 8)

  def test_shipment_subtracts_quantity(self):
    balance = apply_stock_operation_balance(
      5,
      self._op(StockOperation.OperationType.SHIPMENT, 1),
    )
    self.assertEqual(balance, 4)

  def test_inventory_sets_absolute_quantity(self):
    balance = apply_stock_operation_balance(
      10,
      self._op(
        StockOperation.OperationType.ADJUSTMENT,
        7,
        comment="Инвентаризация: насчитано 7 шт. → CRM 7 шт.",
      ),
    )
    self.assertEqual(balance, 7)

  def test_wb_fact_intake_delta(self):
    balance = apply_stock_operation_balance(
      4,
      self._op(StockOperation.OperationType.INTAKE, 2, comment="Факт WB"),
    )
    self.assertEqual(balance, 6)


class DailyStorageCostTests(SimpleTestCase):
  def test_daily_storage_cost_uses_month_length(self):
    from apps.warehouse.services.liter_pricing import daily_storage_cost

    seller = Mock()
    seller.storage_tariff_per_liter_month = Decimal("30")
    amount = daily_storage_cost(
      10,
      Decimal("1"),
      seller=seller,
      charge_date=date(2026, 2, 15),
    )
    self.assertEqual(amount, Decimal("10.71"))
