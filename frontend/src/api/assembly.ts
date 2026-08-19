import { apiFetch } from './client'
import type { PickList } from './orders'

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
  created_at: string
}

export interface AssemblySellerDetail {
  seller: { id: number; company_name: string }
  counts: Record<string, number>
  supplies_forming: number
  orders: AssemblyOrder[]
  active_pick_list: PickList | null
}

export interface StartAssemblyResult {
  success: boolean
  pick_list_id: number
  orders_count: number
  stickers_fetched: number
  sticker_errors: string
  pick_list: PickList | null
}

export interface PrintScanResult {
  success: boolean
  order: {
    id: number
    wb_order_id: number
    barcode: string
    status: string
    status_display: string
    sticker_file: string
    sticker_part_a: string
    sticker_part_b: string
    has_sticker: boolean
  }
}

export function fetchAssemblySellers() {
  return apiFetch<SellerAssemblyCounters[]>('/api/orders/assembly/sellers/')
}

export function fetchAssemblySeller(sellerId: number, stage?: string) {
  const qs = stage ? `?stage=${stage}` : ''
  return apiFetch<AssemblySellerDetail>(`/api/orders/assembly/sellers/${sellerId}/${qs}`)
}

export function startAssembly(sellerId: number) {
  return apiFetch<StartAssemblyResult>(`/api/orders/assembly/sellers/${sellerId}/start/`, {
    method: 'POST',
    body: '{}',
  })
}

export function scanPrintSticker(sellerId: number, barcode: string) {
  return apiFetch<PrintScanResult>(`/api/orders/assembly/sellers/${sellerId}/scan-print/`, {
    method: 'POST',
    body: JSON.stringify({ barcode }),
  })
}
