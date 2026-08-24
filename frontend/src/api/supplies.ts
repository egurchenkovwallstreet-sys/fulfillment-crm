import { apiFetch } from './client'

export interface SupplyOrder {
  id: number
  wb_order_id: number
  barcode: string
  cell_number: string
  status: string
  status_display: string
  has_sticker: boolean
  marking_bound: boolean
  marking_verify_status?: string
  marking_verify_error?: string
  requires_marking: boolean
  can_send_to_delivery: boolean
  block_reason: string | null
}

export interface SupplyItem {
  id: number
  seller: number
  seller_name: string
  wb_supply_id: string
  status: 'forming' | 'ready' | 'confirmed' | 'shipped'
  status_display: string
  orders_count: number
  orders: SupplyOrder[]
  can_deliver: boolean
  supply_barcode_printed: boolean
  stock_deducted: boolean
  created_at: string
  updated_at: string
}

export interface SuppliesSyncStats {
  created: number
  updated: number
  linked_orders: number
  skipped: number
  api_order_fetches: number
  wb_supplies_total: number
  stock_deducted: number
  stock_errors: number
}

export interface SuppliesListResponse {
  supplies: SupplyItem[]
  sync: SuppliesSyncStats
}

export interface SupplyDeliverResponse {
  success: boolean
  message: string
  wb_supply_id: string
  supply_barcode_file?: string
  supply_barcode?: string
}

export interface SupplyBarcodeResponse {
  success: boolean
  supply_barcode_file: string
  supply_barcode: string
}

export interface SupplyBulkDeliverResponse {
  success: boolean
  delivered: number
  errors: Array<{ supply_id: number; wb_supply_id: string; error: string }>
  supply_barcode_files: string[]
}

export function fetchSupplies(
  sellerId: number,
  options?: { status?: string; sync?: boolean },
) {
  const params = new URLSearchParams({ seller_id: String(sellerId) })
  if (options?.status) params.set('status', options.status)
  if (options?.sync === false) params.set('sync', '0')
  return apiFetch<SuppliesListResponse>(`/api/orders/supplies/?${params}`)
}

export function fetchSupplyDetail(supplyId: number) {
  return apiFetch<SupplyItem>(`/api/orders/supplies/${supplyId}/`)
}

export function deliverSupply(supplyId: number) {
  return apiFetch<SupplyDeliverResponse>(`/api/orders/supplies/${supplyId}/deliver/`, {
    method: 'POST',
    body: '{}',
  })
}

export function deliverSuppliesBulk(sellerId: number, supplyIds?: number[]) {
  return apiFetch<SupplyBulkDeliverResponse>('/api/orders/supplies/bulk-deliver/', {
    method: 'POST',
    body: JSON.stringify({
      seller_id: sellerId,
      supply_ids: supplyIds ?? [],
    }),
  })
}

export function fetchSupplyBarcode(supplyId: number) {
  return apiFetch<SupplyBarcodeResponse>(`/api/orders/supplies/${supplyId}/barcode/`)
}
