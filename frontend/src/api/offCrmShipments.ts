import { apiFetch } from './client'

export interface OffCrmSellerSummary {
  seller_id: number
  seller_name: string
  pending_count: number
}

export interface OffCrmShipmentSummary {
  pending_count: number
  sellers: OffCrmSellerSummary[]
}

export interface OffCrmShipmentItem {
  id: number
  wb_order_id: number
  barcode: string
  sticker_number: string
  warehouse_name: string
  wb_warehouse_id: number | null
  quantity: number
  shipped_at: string | null
  wb_supply_id: string
  detected_at: string
}

export interface OffCrmSellerDetail {
  seller_id: number
  seller_name: string
  items: OffCrmShipmentItem[]
}

export function fetchOffCrmSummary() {
  return apiFetch<OffCrmShipmentSummary>('/api/orders/off-crm-shipments/summary/')
}

export function fetchOffCrmSellerDetail(sellerId: number) {
  return apiFetch<OffCrmSellerDetail>(`/api/orders/off-crm-shipments/sellers/${sellerId}/`)
}

export function deductOffCrmShipment(shipmentId: number) {
  return apiFetch<{ shipment_id: number; status: string }>(
    `/api/orders/off-crm-shipments/${shipmentId}/deduct/`,
    { method: 'POST' },
  )
}

export function skipOffCrmShipment(shipmentId: number) {
  return apiFetch<{ shipment_id: number; status: string }>(
    `/api/orders/off-crm-shipments/${shipmentId}/skip/`,
    { method: 'POST' },
  )
}
