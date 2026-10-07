from datetime import timedelta
from decimal import Decimal

from django.test import TestCase

from apps.accounts.models import Fulfillment
from apps.integrations.marketplace import WB
from apps.sellers.models import DailyStorageCharge, Seller
from apps.sellers.services.calendar_periods import today_local
from apps.sellers.services.liter_billing import (
  accrue_daily_storage_for_seller,
  storage_sync_from_date,
)
from apps.warehouse.models import Cell, Product, ProductDailyQuantity


class LiterStorageAccrualTests(TestCase):
  def setUp(self):
    self.fulfillment = Fulfillment.objects.create(slug="storage-ff", name="Storage FF")
    self.seller = Seller.objects.create(
      company_name="Storage Seller",
      fulfillment=self.fulfillment,
      wb_enabled=True,
      storage_tariff_per_liter_month=Decimal("30"),
    )
    self.cell = Cell.objects.create(
      seller=self.seller,
      number="1",
      marketplace=WB,
    )
    self.product = Product.objects.create(
      seller=self.seller,
      cell=self.cell,
      barcode="2048323467207",
      name="Test pants",
      marketplace=WB,
      quantity=10,
      length_cm=Decimal("29"),
      width_cm=Decimal("38"),
      height_cm=Decimal("3"),
      volume_liters=Decimal("3.40"),
    )
    self.today = today_local()
    self.first_day = self.today - timedelta(days=10)
    ProductDailyQuantity.objects.create(
      product=self.product,
      date=self.first_day,
      quantity=10,
    )

  def test_storage_sync_from_date_starts_at_first_positive_without_charges(self):
    from_date = storage_sync_from_date(self.product, self.seller, self.today)
    self.assertEqual(from_date, self.first_day)

  def test_storage_sync_from_date_continues_after_last_charge(self):
    last = self.today - timedelta(days=4)
    DailyStorageCharge.objects.create(
      seller=self.seller,
      product=self.product,
      charge_date=last,
      quantity=10,
      volume_liters=Decimal("3.40"),
      amount=Decimal("10.00"),
    )
    from_date = storage_sync_from_date(self.product, self.seller, self.today)
    self.assertEqual(from_date, last + timedelta(days=1))

  def test_accrue_backfills_missing_days_after_last_charge(self):
    last = self.today - timedelta(days=4)
    DailyStorageCharge.objects.create(
      seller=self.seller,
      product=self.product,
      charge_date=last,
      quantity=10,
      volume_liters=Decimal("3.40"),
      amount=Decimal("10.00"),
    )
    accrue_daily_storage_for_seller(self.seller, charge_date=self.today)
    charges = DailyStorageCharge.objects.filter(
      seller=self.seller,
      product=self.product,
      charge_date__gt=last,
      charge_date__lte=self.today,
    )
    expected_days = (self.today - last).days
    self.assertEqual(charges.count(), expected_days)
    self.assertTrue(all(row.amount > 0 for row in charges))
