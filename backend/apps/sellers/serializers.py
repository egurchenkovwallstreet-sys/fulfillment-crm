from rest_framework import serializers

from apps.sellers.models import SellerWarehouse


class SellerWarehouseSerializer(serializers.ModelSerializer):
  class Meta:
    model = SellerWarehouse
    fields = (
      "id",
      "wb_warehouse_id",
      "name",
      "address",
      "office_id",
      "is_enabled",
      "synced_at",
    )
    read_only_fields = (
      "id",
      "wb_warehouse_id",
      "name",
      "address",
      "office_id",
      "synced_at",
    )


class SellerWarehouseToggleSerializer(serializers.Serializer):
  is_enabled = serializers.BooleanField()
