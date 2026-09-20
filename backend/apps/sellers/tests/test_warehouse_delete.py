from django.test import TestCase

from apps.accounts.models import Fulfillment, User
from apps.sellers.models import ExcludedSellerWarehouse, Seller, SellerWarehouse
from apps.sellers.services.warehouse_manage import WarehouseManageError, delete_seller_wb_warehouse
from apps.warehouse.models import WbFactIntakeSession


class DeleteSellerWarehouseTest(TestCase):
  def setUp(self):
    self.fulfillment = Fulfillment.objects.create(slug="ff-test", name="Test FF")
    self.admin = User.objects.create_user(
      username="admin",
      password="pass",
      role=User.Role.ADMIN,
      fulfillment=self.fulfillment,
    )
    self.seller = Seller.objects.create(
      company_name="ИП Тест",
      fulfillment=self.fulfillment,
      wb_enabled=True,
    )
    self.warehouse = SellerWarehouse.objects.create(
      seller=self.seller,
      wb_warehouse_id=123456,
      name="ФФ центр Рязанский",
      is_enabled=True,
    )

  def test_delete_blocked_by_active_fact_intake(self):
    WbFactIntakeSession.objects.create(
      seller=self.seller,
      warehouse=self.warehouse,
      warehouse_name_snapshot=self.warehouse.name,
      wb_warehouse_id_snapshot=self.warehouse.wb_warehouse_id,
      status=WbFactIntakeSession.Status.SCANNING,
    )

    with self.assertRaises(WarehouseManageError) as ctx:
      delete_seller_wb_warehouse(self.seller, self.warehouse.id, user=self.admin)

    self.assertIn("приёмка карточек WB", str(ctx.exception).lower())
    self.assertTrue(SellerWarehouse.objects.filter(pk=self.warehouse.id).exists())

  def test_delete_succeeds_with_completed_fact_intake(self):
    WbFactIntakeSession.objects.create(
      seller=self.seller,
      warehouse=self.warehouse,
      warehouse_name_snapshot=self.warehouse.name,
      wb_warehouse_id_snapshot=self.warehouse.wb_warehouse_id,
      status=WbFactIntakeSession.Status.COMPLETED,
    )

    result = delete_seller_wb_warehouse(self.seller, self.warehouse.id, user=self.admin)

    self.assertIn("удалён", result["detail"].lower())
    self.assertFalse(SellerWarehouse.objects.filter(pk=self.warehouse.id).exists())
    self.assertTrue(
      ExcludedSellerWarehouse.objects.filter(
        seller=self.seller,
        warehouse_external_id=123456,
      ).exists()
    )
    session = WbFactIntakeSession.objects.get()
    self.assertIsNone(session.warehouse_id)
    self.assertEqual(session.warehouse_name_snapshot, "ФФ центр Рязанский")
    self.assertEqual(session.wb_warehouse_id_snapshot, 123456)
