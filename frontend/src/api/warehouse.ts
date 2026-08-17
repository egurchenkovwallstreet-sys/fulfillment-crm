import { apiFetch } from './client'

export type Seller = {
  id: number
  company_name: string
}

export type Cell = {
  id: number
  number: string
  is_occupied: boolean
}

export type Product = {
  id: number
  barcode: string
  name: string
  quantity: number
  cell: number
  cell_number: string
  seller: number
  seller_name: string
  requires_marking: boolean
}

export type IntakeLookup = {
  exists: boolean
  barcode?: string
  product?: Product
}

export type IntakeHistoryItem = {
  id: number
  barcode: string
  cell_number: string
  seller_name: string
  operation_type: string
  quantity: number
  comment: string
  created_at: string
}

export type IntakePayload = {
  seller_id: number
  barcode: string
  quantity: number
  cell_mode: 'auto' | 'manual'
  cell_id?: number | null
  name?: string
}

export function fetchSellers() {
  return apiFetch<Seller[]>('/api/warehouse/sellers/')
}

export function fetchFreeCells() {
  return apiFetch<Cell[]>('/api/warehouse/cells/?free=1')
}

export function lookupBarcode(sellerId: number, barcode: string) {
  const params = new URLSearchParams({
    seller_id: String(sellerId),
    barcode,
  })
  return apiFetch<IntakeLookup>(`/api/warehouse/intake/lookup/?${params}`)
}

export function submitIntake(payload: IntakePayload) {
  return apiFetch<{ success: boolean; message: string; product: Product }>(
    '/api/warehouse/intake/',
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
  )
}

export function fetchIntakeHistory() {
  return apiFetch<IntakeHistoryItem[]>('/api/warehouse/intake/history/')
}
