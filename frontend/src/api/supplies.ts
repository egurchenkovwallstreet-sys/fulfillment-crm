import { apiFetch } from './client'

export type SupplyStatus = 'forming' | 'ready' | 'confirmed' | 'shipped'

export interface SupplyOrder {
  id: number
  wb_order_id: number
  barcode: string
  cell_number: string
  status: string
  status_display: string
  has_sticker: boolean
  marking_bound: boolean
  requires_marking: boolean
  can_send_to_delivery: boolean
  block_reason: string | null
}

export interface Supply {
  id: number
  seller: number
  seller_name: string
  wb_supply_id: string
  status: SupplyStatus
  status_display: string
  orders_count: number
  orders: SupplyOrder[]
  can_deliver: boolean
  supply_barcode_printed: boolean
  created_at: string
  updated_at: string
}

export interface SupplyDeliverResult {
  success: boolean
  message: string
  wb_supply_id: string
  supply_barcode_file?: string
  supply_barcode?: string
  detail?: string
}

export interface SupplyBulkDeliverResult {
  success: boolean
  message: string
  delivered: number
  errors: Array<{ supply_id: number; wb_supply_id: string; error: string }>
  supply_barcode_files: string[]
}

export interface SupplyBarcodeResult {
  success: boolean
  wb_supply_id: string
  supply_barcode_file: string
  supply_barcode: string
}

export interface SuppliesListResponse {
  supplies: Supply[]
  sync?: {
    created: number
    updated: number
    linked_orders: number
    skipped: number
    api_order_fetches: number
    wb_supplies_total: number
  }
}

export function fetchSupplies(sellerId: number, status?: SupplyStatus | '', sync = true) {
  const params = new URLSearchParams({ seller_id: String(sellerId) })
  if (status) params.set('status', status)
  if (!sync) params.set('sync', '0')
  return apiFetch<SuppliesListResponse | Supply[]>(`/api/orders/supplies/?${params}`)
}

export function deliverSupply(supplyId: number) {
  return apiFetch<SupplyDeliverResult>(`/api/orders/supplies/${supplyId}/deliver/`, {
    method: 'POST',
  })
}

export function deliverSuppliesBulk(sellerId: number, supplyIds?: number[]) {
  return apiFetch<SupplyBulkDeliverResult>('/api/orders/supplies/bulk-deliver/', {
    method: 'POST',
    body: JSON.stringify({
      seller_id: sellerId,
      supply_ids: supplyIds ?? [],
    }),
  })
}

export function fetchSupplyBarcode(supplyId: number) {
  return apiFetch<SupplyBarcodeResult>(`/api/orders/supplies/${supplyId}/barcode/`)
}
