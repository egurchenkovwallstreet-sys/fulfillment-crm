from decimal import Decimal

from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsAdmin
from apps.accounts.tenant import fulfillment_for_staff_user, get_seller_for_user, price_groups_for_user
from apps.warehouse.models import PriceGroup
from apps.warehouse.services.seller_pricing import (
  SellerPricingError,
  apply_seller_liter_tariff,
  apply_seller_tariff,
  get_seller_pricing_summary,
)
from apps.sellers.services.liter_billing import liter_tariff_payload


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


class SellerLiterTariffApplySerializer(serializers.Serializer):
  pricing_mode = serializers.ChoiceField(choices=["per_unit", "per_liter"])
  first_liter_shipment_price = serializers.DecimalField(
    max_digits=10, decimal_places=2, min_value=Decimal("0"), required=False,
  )
  next_liter_shipment_price = serializers.DecimalField(
    max_digits=10, decimal_places=2, min_value=Decimal("0"), required=False,
  )
  marking_surcharge_per_unit = serializers.DecimalField(
    max_digits=10, decimal_places=2, min_value=Decimal("0"), required=False,
  )
  storage_tariff_per_liter_month = serializers.DecimalField(
    max_digits=10, decimal_places=2, min_value=Decimal("0"), required=False,
  )


class PriceGroupListView(APIView):
  permission_classes = [IsAuthenticated, IsAdmin]

  def get(self, request):
    return Response(PriceGroupSerializer(price_groups_for_user(request.user), many=True).data)

  def post(self, request):
    fulfillment = fulfillment_for_staff_user(request.user)
    if not fulfillment:
      return Response({"detail": "Фулфилмент не определён"}, status=status.HTTP_400_BAD_REQUEST)
    serializer = PriceGroupSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    group = serializer.save(fulfillment=fulfillment)
    return Response(PriceGroupSerializer(group).data, status=status.HTTP_201_CREATED)


class PriceGroupDetailView(APIView):
  permission_classes = [IsAuthenticated, IsAdmin]

  def patch(self, request, group_id):
    group = price_groups_for_user(request.user).filter(pk=group_id).first()
    if not group:
      return Response(status=status.HTTP_404_NOT_FOUND)
    serializer = PriceGroupSerializer(group, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    group = serializer.save()
    return Response(PriceGroupSerializer(group).data)

  def delete(self, request, group_id):
    group = price_groups_for_user(request.user).filter(pk=group_id).first()
    if not group:
      return Response(status=status.HTTP_404_NOT_FOUND)
    group.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


class SellerPricingView(APIView):
  permission_classes = [IsAuthenticated, IsAdmin]

  def get(self, request, seller_id):
    seller = get_seller_for_user(request.user, seller_id)
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)
    summary = get_seller_pricing_summary(seller)
    return Response({
      **SellerPricingSummarySerializer(summary).data,
      "liter": liter_tariff_payload(seller),
    })

  def post(self, request, seller_id):
    seller = get_seller_for_user(request.user, seller_id)
    if not seller:
      return Response(status=status.HTTP_404_NOT_FOUND)

    if "pricing_mode" in request.data:
      serializer = SellerLiterTariffApplySerializer(data=request.data)
      serializer.is_valid(raise_exception=True)
      data = serializer.validated_data
      try:
        result = apply_seller_liter_tariff(
          seller,
          pricing_mode=data["pricing_mode"],
          first_liter_shipment_price=data.get("first_liter_shipment_price"),
          next_liter_shipment_price=data.get("next_liter_shipment_price"),
          marking_surcharge_per_unit=data.get("marking_surcharge_per_unit"),
          storage_tariff_per_liter_month=data.get("storage_tariff_per_liter_month"),
        )
      except SellerPricingError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
      summary = get_seller_pricing_summary(seller)
      return Response({
        "result": result,
        "summary": SellerPricingSummarySerializer(summary).data,
        "liter": liter_tariff_payload(seller),
      })

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
      "liter": liter_tariff_payload(seller),
    })
