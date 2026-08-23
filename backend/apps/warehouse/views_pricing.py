from decimal import Decimal

from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsAdmin
from apps.sellers.models import Seller
from apps.warehouse.models import PriceGroup
from apps.warehouse.services.seller_pricing import (
  SellerPricingError,
  apply_seller_tariff,
  get_price_groups,
  get_seller_pricing_summary,
)


class PriceGroupSerializer(serializers.ModelSerializer):
  class Meta:
    model = PriceGroup
    fields = ("id", "name", "processing_price", "sort_order")


class SellerPricingGroupSerializer(serializers.Serializer):
  id = serializers.IntegerField()
  name = serializers.CharField()
  default_price = serializers.DecimalField(max_digits=10, decimal_places=2)
  product_count = serializers.IntegerField()
  tariff = serializers.DecimalField(max_digits=10, decimal_places=2, allow_null=True)
  mixed_tariffs = serializers.BooleanField()


class SellerPricingSummarySerializer(serializers.Serializer):
  seller_id = serializers.IntegerField()
  company_name = serializers.CharField()
  product_count = serializers.IntegerField()
  ungrouped_count = serializers.IntegerField()
  common_tariff = serializers.DecimalField(max_digits=10, decimal_places=2, allow_null=True)
  mixed_common_tariff = serializers.BooleanField()
  groups = SellerPricingGroupSerializer(many=True)


class SellerTariffApplySerializer(serializers.Serializer):
  scope = serializers.ChoiceField(choices=["all", "group"])
  price = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0"))
  price_group_id = serializers.IntegerField(required=False, allow_null=True)
  assign_group = serializers.BooleanField(default=False)

  def validate(self, attrs):
    if attrs["scope"] == "group" and not attrs.get("price_group_id"):
      raise serializers.ValidationError({"price_group_id": "Укажите ценовую группу"})
    return attrs


class PriceGroupListView(APIView):
  permission_classes = [IsAuthenticated, IsAdmin]

  def get(self, request):
    return Response(PriceGroupSerializer(get_price_groups(), many=True).data)


class SellerPricingView(APIView):
  permission_classes = [IsAuthenticated, IsAdmin]

  def get(self, request, seller_id):
    seller = get_object_or_404(Seller, pk=seller_id)
    summary = get_seller_pricing_summary(seller)
    return Response(SellerPricingSummarySerializer(summary).data)

  def post(self, request, seller_id):
    seller = get_object_or_404(Seller, pk=seller_id)
    serializer = SellerTariffApplySerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    try:
      result = apply_seller_tariff(
        seller,
        scope=data["scope"],
        price=data["price"],
        price_group_id=data.get("price_group_id"),
        assign_group=data.get("assign_group", False),
      )
    except SellerPricingError as exc:
      return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    summary = get_seller_pricing_summary(seller)
    return Response({
      "result": result,
      "summary": SellerPricingSummarySerializer(summary).data,
    })
