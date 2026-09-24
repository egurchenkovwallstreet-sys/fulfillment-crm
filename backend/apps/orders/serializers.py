from rest_framework import serializers

from apps.sellers.models import Seller

from .models import Order, PickList, PickListItem, Supply


def _resolve_order_product(order: Order, serializer=None):
  if order.product_id:
    product = getattr(order, "product", None)
    if product is not None:
      return product
  from apps.integrations.marketplace import WB as MARKETPLACE_WB
  from apps.warehouse.services.product_lookup import resolve_product_by_barcode

  ctx = serializer.context if serializer is not None else {}
  return resolve_product_by_barcode(
    order.seller,
    MARKETPLACE_WB,
    order.barcode,
    select_cell=True,
    catalog_index=ctx.get("wb_catalog_index"),
    chrt_product_map=ctx.get("chrt_product_map"),
    register_alias=True,
  )


class OrderSerializer(serializers.ModelSerializer):
  seller_name = serializers.CharField(source="seller.company_name", read_only=True)
  cell_number = serializers.CharField(source="product.cell.number", read_only=True, default="")
  status_display = serializers.CharField(source="get_status_display", read_only=True)

  class Meta:
    model = Order
    fields = (
      "id",
      "wb_order_id",
      "barcode",
      "seller",
      "seller_name",
      "cell_number",
      "status",
      "status_display",
      "has_sticker",
      "marking_bound",
      "created_at",
    )


class OrderAssemblySerializer(serializers.ModelSerializer):
  cell_number = serializers.SerializerMethodField()
  status_display = serializers.CharField(source="get_status_display", read_only=True)
  wb_stage_display = serializers.SerializerMethodField()
  requires_marking = serializers.SerializerMethodField()
  alternate_barcodes = serializers.SerializerMethodField()
  can_send_to_assembly = serializers.SerializerMethodField()
  can_send_to_delivery = serializers.SerializerMethodField()
  can_move_to_new_supply = serializers.SerializerMethodField()

  warehouse_quantity = serializers.SerializerMethodField()
  photo_url = serializers.SerializerMethodField()
  tech_size = serializers.SerializerMethodField()

  class Meta:
    model = Order
    fields = (
      "id",
      "wb_order_id",
      "barcode",
      "cell_number",
      "photo_url",
      "tech_size",
      "status",
      "status_display",
      "wb_supplier_status",
      "wb_status",
      "wb_stage_display",
      "has_sticker",
      "sticker_part_a",
      "sticker_part_b",
      "sticker_scan_code",
      "marking_bound",
      "marking_verify_status",
      "marking_verify_error",
      "requires_marking",
      "alternate_barcodes",
      "can_send_to_assembly",
      "can_send_to_delivery",
      "can_move_to_new_supply",
      "warehouse_quantity",
      "created_at",
    )

  def get_alternate_barcodes(self, obj):
    from apps.warehouse.models import ProductBarcodeAlias
    from apps.warehouse.services.catalog_fetch import normalize_barcode

    product = _resolve_order_product(obj, self)
    product_id = product.id if product else None
    if not product_id:
      return []
    primary = normalize_barcode(obj.barcode)
    aliases = ProductBarcodeAlias.objects.filter(product_id=product_id).values_list(
      "barcode",
      flat=True,
    )
    return [code for code in aliases if normalize_barcode(code) != primary]

  def get_wb_stage_display(self, obj):
    from apps.orders.services.assembly import get_wb_stage_label
    from apps.orders.services.wb_status import get_wb_status_label, is_wb_cancelled

    if obj.status == Order.Status.CANCELLED or is_wb_cancelled(
      obj.wb_supplier_status,
      obj.wb_status,
    ):
      wb_label = get_wb_status_label(obj.wb_status)
      if wb_label and wb_label not in ("—", obj.wb_status):
        return wb_label
      supplier_label = get_wb_stage_label(obj.wb_supplier_status)
      if supplier_label and supplier_label not in ("—", obj.wb_supplier_status):
        return supplier_label
      return "Отменён"
    return get_wb_stage_label(obj.wb_supplier_status)

  def get_cell_number(self, obj):
    product = _resolve_order_product(obj, self)
    if product and product.cell_id:
      return str(product.cell.number)
    return ""

  def get_requires_marking(self, obj):
    from apps.warehouse.services.marking_lookup import resolve_product_requires_marking

    product = _resolve_order_product(obj, self)
    return resolve_product_requires_marking(product, obj.barcode, obj.seller)

  def get_can_send_to_assembly(self, obj):
    from apps.orders.services.supply_flow import order_can_send_to_assembly
    return order_can_send_to_assembly(obj)

  def get_can_send_to_delivery(self, obj):
    from apps.orders.services.supply_flow import order_can_send_to_delivery
    return order_can_send_to_delivery(obj)

  def get_can_move_to_new_supply(self, obj):
    from apps.orders.services.supply_flow import order_can_move_to_new_supply
    return order_can_move_to_new_supply(obj)

  def get_warehouse_quantity(self, obj):
    product = _resolve_order_product(obj, self)
    return product.quantity if product else None

  def get_photo_url(self, obj):
    product = _resolve_order_product(obj, self)
    return (product.photo_url or "").strip() if product else ""

  def get_tech_size(self, obj):
    product = _resolve_order_product(obj, self)
    if not product:
      return ""
    return (product.tech_size or product.wb_size or "").strip()


class OrderPrintSerializer(serializers.ModelSerializer):
  status_display = serializers.CharField(source="get_status_display", read_only=True)
  cell_number = serializers.SerializerMethodField()
  requires_marking = serializers.SerializerMethodField()
  marking_bound = serializers.BooleanField(read_only=True)
  can_send_to_delivery = serializers.SerializerMethodField()
  wb_supply_id = serializers.SerializerMethodField()
  supply_created_at = serializers.SerializerMethodField()

  class Meta:
    model = Order
    fields = (
      "id",
      "wb_order_id",
      "barcode",
      "cell_number",
      "status",
      "status_display",
      "sticker_file",
      "sticker_part_a",
      "sticker_part_b",
      "sticker_scan_code",
      "has_sticker",
      "requires_marking",
      "marking_bound",
      "marking_verify_status",
      "marking_verify_error",
      "can_send_to_delivery",
      "wb_supply_id",
      "supply_created_at",
    )

  def get_cell_number(self, obj):
    product = _resolve_order_product(obj, self)
    if product and product.cell_id:
      return str(product.cell.number)
    return ""

  def get_requires_marking(self, obj):
    from apps.warehouse.services.marking_lookup import resolve_product_requires_marking

    product = _resolve_order_product(obj, self)
    return resolve_product_requires_marking(product, obj.barcode, obj.seller)

  def get_can_send_to_delivery(self, obj):
    from apps.orders.services.supply_flow import order_can_send_to_delivery
    return order_can_send_to_delivery(obj)

  def get_wb_supply_id(self, obj):
    supply = self._primary_supply(obj)
    return (supply.wb_supply_id or "").strip() if supply else ""

  def get_supply_created_at(self, obj):
    supply = self._primary_supply(obj)
    if not supply or not supply.created_at:
      return None
    return supply.created_at.isoformat()

  def _primary_supply(self, obj):
    supplies = getattr(obj, "_prefetched_objects_cache", {}).get("supplies")
    if supplies is not None:
      items = list(supplies)
    else:
      items = list(obj.supplies.all())
    if not items:
      return None
    active = (
      Supply.Status.FORMING,
      Supply.Status.READY,
      Supply.Status.CONFIRMED,
    )
    for supply in sorted(items, key=lambda item: item.updated_at, reverse=True):
      if supply.status in active and (supply.wb_supply_id or "").strip():
        return supply
    return max(items, key=lambda item: item.updated_at)


class PickListItemSerializer(serializers.ModelSerializer):
  cell_number = serializers.SerializerMethodField()
  product_name = serializers.SerializerMethodField()
  wb_nm_id = serializers.SerializerMethodField()
  wb_article = serializers.SerializerMethodField()
  tech_size = serializers.SerializerMethodField()
  color_label = serializers.SerializerMethodField()
  requires_marking = serializers.SerializerMethodField()
  alternate_barcodes = serializers.SerializerMethodField()

  class Meta:
    model = PickListItem
    fields = (
      "id",
      "cell_number",
      "barcode",
      "alternate_barcodes",
      "product_name",
      "wb_nm_id",
      "wb_article",
      "tech_size",
      "color_label",
      "requires_marking",
      "quantity",
      "picked_quantity",
    )

  def get_cell_number(self, obj):
    if obj.cell_id:
      return obj.cell.number
    return "—"

  def get_product_name(self, obj):
    if obj.product_id:
      return obj.product.name
    return "—"

  def get_wb_nm_id(self, obj):
    if not obj.product_id:
      return None
    return obj.product.wb_nm_id

  def get_wb_article(self, obj):
    if not obj.product_id:
      return "—"
    product = obj.product
    if product.wb_nm_id:
      return str(product.wb_nm_id)
    return (product.vendor_code or "").strip() or "—"

  def get_tech_size(self, obj):
    if not obj.product_id:
      return "—"
    product = obj.product
    return (product.tech_size or product.wb_size or "").strip() or "—"

  def get_color_label(self, obj):
    if not obj.product_id:
      return ""
    return (obj.product.color_label or "").strip()

  def get_requires_marking(self, obj):
    from apps.warehouse.services.marking_lookup import resolve_product_requires_marking

    seller = obj.pick_list.seller if obj.pick_list_id else None
    if not seller:
      return bool(obj.product.requires_marking) if obj.product_id else False
    return resolve_product_requires_marking(obj.product, obj.barcode, seller)

  def get_alternate_barcodes(self, obj):
    from apps.warehouse.services.product_lookup import product_alternate_barcodes

    if not obj.product_id:
      return []
    return product_alternate_barcodes(obj.product)


class PickListSerializer(serializers.ModelSerializer):
  seller_name = serializers.CharField(source="seller.company_name", read_only=True)
  items = serializers.SerializerMethodField()
  items_count = serializers.SerializerMethodField()
  total_quantity = serializers.SerializerMethodField()

  class Meta:
    model = PickList
    fields = (
      "id",
      "seller",
      "seller_name",
      "wb_warehouse_id",
      "warehouse_name",
      "is_completed",
      "created_at",
      "items",
      "items_count",
      "total_quantity",
    )

  def get_items(self, obj):
    from apps.orders.services.pick_list import _cell_sort_key

    items = list(obj.items.select_related("cell", "product").all())
    items.sort(
      key=lambda item: (
        _cell_sort_key(str(item.cell.number) if item.cell_id else "—"),
        item.sort_order or 0,
        item.id,
      ),
    )
    return PickListItemSerializer(items, many=True).data

  def get_items_count(self, obj):
    return obj.items.count()

  def get_total_quantity(self, obj):
    return sum(item.quantity for item in obj.items.all())


class PickListBriefSerializer(serializers.ModelSerializer):
  seller_name = serializers.CharField(source="seller.company_name", read_only=True)
  items_count = serializers.SerializerMethodField()
  total_quantity = serializers.SerializerMethodField()

  class Meta:
    model = PickList
    fields = (
      "id",
      "seller",
      "seller_name",
      "warehouse_name",
      "wb_warehouse_id",
      "is_completed",
      "created_at",
      "items_count",
      "total_quantity",
    )

  def get_items_count(self, obj):
    return obj.items.count()

  def get_total_quantity(self, obj):
    return sum(item.quantity for item in obj.items.all())


class SellerAssemblyCountersSerializer(serializers.Serializer):
  id = serializers.IntegerField()
  company_name = serializers.CharField()
  new = serializers.IntegerField()
  in_picking = serializers.IntegerField()
  in_delivery = serializers.IntegerField()
  assembled = serializers.IntegerField()
  label_printed = serializers.IntegerField()
  marked = serializers.IntegerField()
  in_supply = serializers.IntegerField()
  shipped = serializers.IntegerField()
  cancelled = serializers.IntegerField(required=False)
  total_active = serializers.IntegerField()
  marketplace = serializers.CharField(required=False)
  has_ozon_api = serializers.BooleanField(required=False)


class OrderSyncSerializer(serializers.Serializer):
  seller_id = serializers.IntegerField(required=False, allow_null=True)
  mode = serializers.ChoiceField(
    choices=["full", "quick", "delivery"],
    default="full",
    required=False,
  )
  background = serializers.BooleanField(required=False, default=True)

  def validate_seller_id(self, value):
    if value is None:
      return value
    if not Seller.objects.filter(pk=value, is_active=True).exists():
      raise serializers.ValidationError("Селлер не найден или неактивен")
    return value


class PickListGenerateSerializer(serializers.Serializer):
  seller_id = serializers.IntegerField()
  force = serializers.BooleanField(required=False, default=False)
  stage = serializers.ChoiceField(choices=["new", "confirm"], required=False, default="new")

  def validate_seller_id(self, value):
    if not Seller.objects.filter(pk=value, is_active=True).exists():
      raise serializers.ValidationError("Селлер не найден или неактивен")
    return value


class AssemblyBindMarkingOrderSerializer(serializers.ModelSerializer):
  """Ответ bind-marking / scan await_marking без sticker_file — стикер в кэше браузера."""

  status_display = serializers.CharField(source="get_status_display", read_only=True)
  requires_marking = serializers.SerializerMethodField()

  class Meta:
    model = Order
    fields = (
      "id",
      "wb_order_id",
      "barcode",
      "status",
      "status_display",
      "has_sticker",
      "requires_marking",
      "marking_bound",
      "marking_verify_status",
      "marking_verify_error",
    )

  def get_requires_marking(self, obj):
    from apps.warehouse.services.marking_lookup import resolve_product_requires_marking

    product = _resolve_order_product(obj, self)
    return resolve_product_requires_marking(product, obj.barcode, obj.seller)


class AssemblyStickerCacheSerializer(serializers.ModelSerializer):
  """Стикер одного заказа для кэша браузера после fetch-stickers."""

  class Meta:
    model = Order
    fields = (
      "id",
      "wb_order_id",
      "has_sticker",
      "sticker_file",
      "sticker_part_a",
      "sticker_part_b",
    )


class ScanPrintSerializer(serializers.Serializer):
  barcode = serializers.CharField(max_length=200)


class BindMarkingSerializer(serializers.Serializer):
  order_id = serializers.IntegerField()
  marking_code = serializers.CharField(max_length=500)


class VerifyMarkingSerializer(serializers.Serializer):
  order_ids = serializers.ListField(
    child=serializers.IntegerField(),
    required=False,
    allow_empty=True,
  )
  force_recheck = serializers.BooleanField(required=False, default=True)


class PushMarkingWbSerializer(serializers.Serializer):
  order_ids = serializers.ListField(
    child=serializers.IntegerField(),
    required=False,
    allow_empty=True,
  )
  force = serializers.BooleanField(required=False, default=False)
  repair = serializers.BooleanField(required=False, default=False)


class ReplaceOrderSerializer(serializers.Serializer):
  order_id = serializers.IntegerField()


class ResetAssemblyMarkingSerializer(serializers.Serializer):
  order_ids = serializers.ListField(
    child=serializers.IntegerField(),
    required=False,
    allow_empty=True,
  )


class OrderActionSerializer(serializers.Serializer):
  order_id = serializers.IntegerField()


class SendToDeliverySerializer(serializers.Serializer):
  order_id = serializers.IntegerField()
  shipping_point_id = serializers.IntegerField()
  shipping_date = serializers.DateField()
  shipping_type = serializers.ChoiceField(
    choices=("selfShipping", "transportCompany"),
    default="selfShipping",
    required=False,
  )


class MoveOrdersToNewSupplySerializer(serializers.Serializer):
  order_ids = serializers.ListField(
    child=serializers.IntegerField(),
    min_length=1,
    max_length=100,
  )
  wb_supply_id = serializers.CharField(required=False, allow_blank=True, default="")


class SupplyDeliverSerializer(serializers.Serializer):
  shipping_point_id = serializers.IntegerField()
  shipping_date = serializers.DateField()
  shipping_type = serializers.ChoiceField(
    choices=("selfShipping", "transportCompany"),
    default="selfShipping",
    required=False,
  )
  force = serializers.BooleanField(required=False, default=False)


class ReprintStickerSerializer(serializers.Serializer):
  order_id = serializers.IntegerField()
  confirmed = serializers.BooleanField()


class AssemblyWorkflowModeSerializer(serializers.Serializer):
  mode = serializers.ChoiceField(choices=("scan", "batch"))


class BatchBindScanSerializer(serializers.Serializer):
  scan = serializers.CharField(max_length=500, required=False, allow_blank=True)
  barcode = serializers.CharField(max_length=200, required=False, allow_blank=True)
  sticker_scan = serializers.CharField(max_length=200, required=False, allow_blank=True)
  marking_code = serializers.CharField(max_length=500, required=False, allow_blank=True)


class SupplyOrderSerializer(serializers.ModelSerializer):
  cell_number = serializers.SerializerMethodField()
  status_display = serializers.CharField(source="get_status_display", read_only=True)
  requires_marking = serializers.SerializerMethodField()
  can_send_to_delivery = serializers.SerializerMethodField()
  block_reason = serializers.SerializerMethodField()

  class Meta:
    model = Order
    fields = (
      "id",
      "wb_order_id",
      "barcode",
      "cell_number",
      "status",
      "status_display",
      "has_sticker",
      "marking_bound",
      "marking_verify_status",
      "marking_verify_error",
      "requires_marking",
      "can_send_to_delivery",
      "block_reason",
    )

  def get_cell_number(self, obj):
    product = _resolve_order_product(obj, self)
    if product and product.cell_id:
      return str(product.cell.number)
    return ""

  def get_requires_marking(self, obj):
    from apps.warehouse.services.marking_lookup import resolve_product_requires_marking

    product = _resolve_order_product(obj, self)
    return resolve_product_requires_marking(product, obj.barcode, obj.seller)

  def get_can_send_to_delivery(self, obj):
    from apps.orders.services.supply_flow import order_can_send_to_delivery
    return order_can_send_to_delivery(obj)

  def get_block_reason(self, obj):
    from apps.orders.services.supply_flow import order_delivery_block_reason
    return order_delivery_block_reason(obj)


class SupplySerializer(serializers.ModelSerializer):
  seller_name = serializers.CharField(source="seller.company_name", read_only=True)
  status_display = serializers.CharField(source="get_status_display", read_only=True)
  warehouse_name = serializers.SerializerMethodField()
  orders = serializers.SerializerMethodField()
  orders_count = serializers.SerializerMethodField()
  can_deliver = serializers.SerializerMethodField()
  can_force_deliver = serializers.SerializerMethodField()

  class Meta:
    model = Supply
    fields = (
      "id",
      "seller",
      "seller_name",
      "wb_supply_id",
      "wb_warehouse_id",
      "warehouse_name",
      "status",
      "status_display",
      "orders_count",
      "orders",
      "can_deliver",
      "can_force_deliver",
      "supply_barcode_printed",
      "stock_deducted",
      "created_at",
      "updated_at",
    )

  def get_warehouse_name(self, obj):
    if obj.wb_warehouse_id is None:
      return ""
    from apps.sellers.models import SellerWarehouse
    warehouse = SellerWarehouse.objects.filter(
      seller=obj.seller,
      wb_warehouse_id=obj.wb_warehouse_id,
    ).first()
    if warehouse and warehouse.name:
      return warehouse.name
    return f"Склад #{obj.wb_warehouse_id}"

  def _assembly_orders_qs(self, obj):
    from apps.sellers.services.warehouse_filter import filter_orders_for_assembly
    seller = self.context.get("seller") or obj.seller
    return filter_orders_for_assembly(
      obj.orders.select_related("product", "product__cell", "seller"),
      seller,
    )

  def get_orders(self, obj):
    order_data_map = self.context.get("order_data_map")
    assembly_orders = list(self._assembly_orders_qs(obj))
    if order_data_map is not None:
      return [
        order_data_map[order.id]
        for order in assembly_orders
        if order.id in order_data_map
      ]
    return OrderAssemblySerializer(assembly_orders, many=True, context=self.context).data

  def get_orders_count(self, obj):
    return self._assembly_orders_qs(obj).count()

  def get_can_deliver(self, obj):
    from apps.orders.services.supply_flow import supply_can_deliver
    seller = self.context.get("seller") or obj.seller
    return supply_can_deliver(obj, seller=seller)

  def get_can_force_deliver(self, obj):
    from apps.orders.services.supply_flow import supply_can_force_deliver
    seller = self.context.get("seller") or obj.seller
    return supply_can_force_deliver(obj, seller=seller)


class DeliverySupplySerializer(serializers.ModelSerializer):
  orders_count = serializers.IntegerField(read_only=True, required=False, default=0)

  class Meta:
    model = Supply
    fields = (
      "id",
      "wb_supply_id",
      "wb_warehouse_id",
      "orders_count",
      "supply_barcode_printed",
      "created_at",
    )


class SupplyBulkDeliverSerializer(serializers.Serializer):
  seller_id = serializers.IntegerField()
  supply_ids = serializers.ListField(
    child=serializers.IntegerField(),
    required=False,
    allow_empty=True,
  )
  shipping_point_id = serializers.IntegerField()
  shipping_date = serializers.DateField()
  shipping_type = serializers.ChoiceField(
    choices=("selfShipping", "transportCompany"),
    default="selfShipping",
    required=False,
  )

  def validate_seller_id(self, value):
    if not Seller.objects.filter(pk=value, is_active=True).exists():
      raise serializers.ValidationError("Селлер не найден или неактивен")
    return value
