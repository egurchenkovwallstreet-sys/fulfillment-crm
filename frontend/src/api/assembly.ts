import { apiFetch } from './client'
import type { PickList } from './orders'
import type { SellerWarehouse } from './sellers'

export interface SellerAssemblyCounters {
  id: number
  company_name: string
  new: number
  in_picking: number
  in_delivery: number
  assembled: number
  label_printed: number
  marked: number
  in_supply: number
  shipped: number
  cancelled?: number
  total_active: number
}

export interface AssemblyOrder {
  id: number
  wb_order_id: number
  barcode: string
  photo_url: string
  tech_size: string
  cell_number: string
  status: string
  status_display: string
  wb_supplier_status: string
  wb_status: string
  wb_stage_display: string
  has_sticker: boolean
  sticker_part_a: string
  sticker_part_b: string
  marking_bound: boolean
  marking_verify_status?: string
  marking_verify_error?: string
  requires_marking: boolean
  can_send_to_assembly: boolean
  can_send_to_delivery: boolean
  warehouse_quantity: number | null
  created_at: string
}

export interface AssemblySellerDetail {
  seller: { id: number; company_name: string }
  counts: Record<string, number>
  assembly_eligible: number
  supplies_forming: number
  warehouses: SellerWarehouse[]
  orders: AssemblyOrder[]
  active_pick_list: PickList | null
}

export interface StartAssemblyResult {
  success: boolean
  pick_list_id: number
  orders_count: number
  wb_assembly_sent?: number
  wb_assembly_errors?: string[]
  stickers_fetched: number
  sticker_errors: string
  pick_list: PickList | null
}

export interface PrintOrder {
  id: number
  wb_order_id: number
  barcode: string
  status: string
  status_display: string
  sticker_file: string
  sticker_part_a: string
  sticker_part_b: string
  has_sticker: boolean
  requires_marking: boolean
  marking_bound: boolean
  marking_verify_status?: string
  marking_verify_error?: string
  cell_number?: string
  can_send_to_delivery: boolean
}

export interface ScanBarcodeResult {
  success: boolean
  action: 'print' | 'await_marking'
  requires_marking: boolean
  message?: string
  order: PrintOrder
}

export interface BindMarkingResult {
  success: boolean
  action: 'await_verification' | 'print'
  message?: string
  order: PrintOrder
}

export interface MarkingVerifyItem {
  order_id: number
  wb_order_id: number
  status: 'pending' | 'verified' | 'error'
  decision: string
  error: string
  marking_bound: boolean
  order?: PrintOrder
}

export interface VerifyMarkingResult {
  success: boolean
  results: MarkingVerifyItem[]
}

export interface ReplaceOrderResult {
  success: boolean
  message: string
  order: AssemblyOrder
}

export interface SendToAssemblyResult {
  success: boolean
  order: AssemblyOrder
  wb_supply_id: string
  stickers_fetched: number
  sticker_error?: string
}

export interface SendAllToAssemblyResult {
  success: boolean
  sent: number
  total: number
  stickers_fetched: number
  errors: Array<{ order_id: number; wb_order_id: number; error: string }>
}

export interface SendToDeliveryResult {
  success: boolean
  order: AssemblyOrder
  wb_supply_id: string
  supply_barcode_file?: string
  supply_barcode?: string
  stock?: {
    deducted: boolean
    already_deducted: boolean
    quantity: number
    cell_number: string
    barcode: string
  }
}

export function fetchAssemblySellers() {
  return apiFetch<SellerAssemblyCounters[]>('/api/orders/assembly/sellers/')
}

export function fetchAssemblySeller(sellerId: number, stage?: string) {
  const qs = stage ? `?stage=${stage}` : ''
  return apiFetch<AssemblySellerDetail>(`/api/orders/assembly/sellers/${sellerId}/${qs}`)
}

export function reprintOrderSticker(sellerId: number, orderId: number) {
  return apiFetch<ScanBarcodeResult>(
    `/api/orders/assembly/sellers/${sellerId}/reprint-sticker/`,
    {
      method: 'POST',
      body: JSON.stringify({ order_id: orderId }),
    },
  )
}

export function startAssembly(sellerId: number) {
  return apiFetch<StartAssemblyResult>(`/api/orders/assembly/sellers/${sellerId}/start/`, {
    method: 'POST',
    body: '{}',
  })
}

export interface DeletePickListResult {
  success: boolean
  deleted_pick_list_id: number
  orders_unlocked: number
}

export function deletePickList(sellerId: number, pickListId?: number) {
  return apiFetch<DeletePickListResult>(
    `/api/orders/assembly/sellers/${sellerId}/delete-pick-list/`,
    {
      method: 'POST',
      body: JSON.stringify(pickListId ? { pick_list_id: pickListId } : {}),
    },
  )
}

export function scanOrderBarcode(sellerId: number, barcode: string) {
  return apiFetch<ScanBarcodeResult>(`/api/orders/assembly/sellers/${sellerId}/scan-print/`, {
    method: 'POST',
    body: JSON.stringify({ barcode }),
  })
}

export function bindMarking(sellerId: number, orderId: number, markingCode: string) {
  return apiFetch<BindMarkingResult>(`/api/orders/assembly/sellers/${sellerId}/bind-marking/`, {
    method: 'POST',
    body: JSON.stringify({ order_id: orderId, marking_code: markingCode }),
  })
}

export function verifyMarking(sellerId: number, orderIds?: number[]) {
  return apiFetch<VerifyMarkingResult>(`/api/orders/assembly/sellers/${sellerId}/verify-marking/`, {
    method: 'POST',
    body: JSON.stringify({ order_ids: orderIds ?? [] }),
  })
}

export function replaceOrderItem(sellerId: number, orderId: number) {
  return apiFetch<ReplaceOrderResult>(`/api/orders/assembly/sellers/${sellerId}/replace-order/`, {
    method: 'POST',
    body: JSON.stringify({ order_id: orderId }),
  })
}

export function sendOrderToAssembly(sellerId: number, orderId: number) {
  return apiFetch<SendToAssemblyResult>(
    `/api/orders/assembly/sellers/${sellerId}/send-to-assembly/`,
    {
      method: 'POST',
      body: JSON.stringify({ order_id: orderId }),
    },
  )
}

export function sendAllOrdersToAssembly(sellerId: number) {
  return apiFetch<SendAllToAssemblyResult>(
    `/api/orders/assembly/sellers/${sellerId}/send-all-to-assembly/`,
    {
      method: 'POST',
      body: '{}',
    },
  )
}

export function sendOrderToDelivery(sellerId: number, orderId: number) {
  return apiFetch<SendToDeliveryResult>(
    `/api/orders/assembly/sellers/${sellerId}/send-to-delivery/`,
    {
      method: 'POST',
      body: JSON.stringify({ order_id: orderId }),
    },
  )
}

/** @deprecated use scanOrderBarcode */
export function scanPrintSticker(sellerId: number, barcode: string) {
  return scanOrderBarcode(sellerId, barcode)
}
