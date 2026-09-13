from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Fulfillment
from apps.integrations.marketplace import OZON
from apps.orders.models import OzonPosting
from apps.sellers.models import Seller, ShipmentUnitCharge
from apps.sellers.services.ozon_billing_stats import load_weekly_ozon_shipped_orders
from apps.sellers.services.unit_billing import (
  TARIFF_APPLY_FROM_TODAY,
  TARIFF_APPLY_RECALCULATE_ALL,
  apply_tariff_billing_policy,
  record_shipment_unit_charge_for_ozon_posting,
  rebuild_ozon_unit_shipment_charges,
)
from apps.warehouse.models import Cell, Product


class TariffBillingTests(TestCase):
  def setUp(self):
    self.fulfillment = Fulfillment.objects.create(slug="test-ff", name="Test FF")
    self.seller = Seller.objects.create(
      company_name="Test Seller",
      fulfillment=self.fulfillment,
      pricing_mode=Seller.PricingMode.PER_UNIT,
    )
    self.cell = Cell.objects.create(
      seller=self.seller,
      number="A-1",
      marketplace=OZON,
    )
    self.product = Product.objects.create(
      seller=self.seller,
      cell=self.cell,
      barcode="4601234567890",
      name="Test product",
      marketplace=OZON,
      individual_price=Decimal("50.00"),
      quantity=10,
    )

  def test_record_unit_charge_for_ozon_posting(self):
    posting = OzonPosting.objects.create(
      seller=self.seller,
      posting_number="123-1",
      ozon_status="awaiting_deliver",
      barcode=self.product.barcode,
      quantity=2,
      shipped_at=timezone.now(),
    )
    charge = record_shipment_unit_charge_for_ozon_posting(posting, seller=self.seller)
    self.assertIsNotNone(charge)
    assert charge is not None
    self.assertEqual(charge.amount, Decimal("100.00"))
    self.assertEqual(charge.unit_price, Decimal("50.00"))

  def test_billing_stats_fallback_to_tariff_without_charge(self):
    old_date = timezone.localdate() - timedelta(days=3)
    OzonPosting.objects.create(
      seller=self.seller,
      posting_number="123-fallback",
      ozon_status="awaiting_deliver",
      barcode=self.product.barcode,
      quantity=2,
      shipped_at=timezone.make_aware(datetime.combine(old_date, datetime.min.time())),
    )
    payload = load_weekly_ozon_shipped_orders(self.seller)
    total_amount = sum(week["total_amount"] for week in payload["weeks"])
    self.assertEqual(total_amount, Decimal("100.00"))

  def test_billing_stats_use_persisted_charges(self):
    old_date = timezone.localdate() - timedelta(days=10)
    posting = OzonPosting.objects.create(
      seller=self.seller,
      posting_number="123-2",
      ozon_status="awaiting_deliver",
      barcode=self.product.barcode,
      quantity=1,
      shipped_at=timezone.make_aware(datetime.combine(old_date, datetime.min.time())),
    )
    ShipmentUnitCharge.objects.create(
      seller=self.seller,
      product=self.product,
      barcode=self.product.barcode,
      marketplace=OZON,
      ozon_posting=posting,
      charge_date=old_date,
      quantity=1,
      unit_price=Decimal("30.00"),
      amount=Decimal("30.00"),
    )
    self.product.individual_price = Decimal("99.00")
    self.product.save(update_fields=["individual_price"])

    payload = load_weekly_ozon_shipped_orders(self.seller)
    total_amount = sum(
      week["total_amount"]
      for week in payload["weeks"]
    )
    self.assertEqual(total_amount, Decimal("30.00"))

  def test_rebuild_ozon_from_today_keeps_old_charges(self):
    old_date = timezone.localdate() - timedelta(days=5)
    today = timezone.localdate()
    posting_old = OzonPosting.objects.create(
      seller=self.seller,
      posting_number="123-old",
      ozon_status="awaiting_deliver",
      barcode=self.product.barcode,
      quantity=1,
      shipped_at=timezone.make_aware(datetime.combine(old_date, datetime.min.time())),
    )
    posting_today = OzonPosting.objects.create(
      seller=self.seller,
      posting_number="123-today",
      ozon_status="awaiting_deliver",
      barcode=self.product.barcode,
      quantity=1,
      shipped_at=timezone.now(),
    )
    ShipmentUnitCharge.objects.create(
      seller=self.seller,
      product=self.product,
      barcode=self.product.barcode,
      marketplace=OZON,
      ozon_posting=posting_old,
      charge_date=old_date,
      quantity=1,
      unit_price=Decimal("30.00"),
      amount=Decimal("30.00"),
    )
    self.product.individual_price = Decimal("80.00")
    self.product.save(update_fields=["individual_price"])

    rebuild_ozon_unit_shipment_charges(self.seller, mode=TARIFF_APPLY_FROM_TODAY)

    old_charge = ShipmentUnitCharge.objects.get(ozon_posting=posting_old)
    today_charge = ShipmentUnitCharge.objects.get(ozon_posting=posting_today)
    self.assertEqual(old_charge.amount, Decimal("30.00"))
    self.assertEqual(today_charge.amount, Decimal("80.00"))

  def test_rebuild_ozon_recalculate_all_updates_history(self):
    old_date = timezone.localdate() - timedelta(days=5)
    posting = OzonPosting.objects.create(
      seller=self.seller,
      posting_number="123-recalc",
      ozon_status="awaiting_deliver",
      barcode=self.product.barcode,
      quantity=1,
      shipped_at=timezone.make_aware(datetime.combine(old_date, datetime.min.time())),
    )
    ShipmentUnitCharge.objects.create(
      seller=self.seller,
      product=self.product,
      barcode=self.product.barcode,
      marketplace=OZON,
      ozon_posting=posting,
      charge_date=old_date,
      quantity=1,
      unit_price=Decimal("30.00"),
      amount=Decimal("30.00"),
    )
    self.product.individual_price = Decimal("80.00")
    self.product.save(update_fields=["individual_price"])

    rebuild_ozon_unit_shipment_charges(self.seller, mode=TARIFF_APPLY_RECALCULATE_ALL)

    charge = ShipmentUnitCharge.objects.get(ozon_posting=posting)
    self.assertEqual(charge.amount, Decimal("80.00"))

  @patch("apps.sellers.services.unit_billing.rebuild_wb_unit_shipment_charges", return_value=0)
  def test_apply_tariff_billing_policy_returns_mode(self, _mock_wb):
    result = apply_tariff_billing_policy(self.seller, TARIFF_APPLY_FROM_TODAY)
    self.assertEqual(result["mode"], TARIFF_APPLY_FROM_TODAY)
