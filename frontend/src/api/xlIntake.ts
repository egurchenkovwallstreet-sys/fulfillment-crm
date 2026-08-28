import { apiFetch } from './client'
import { getAccessToken } from './tokens'
import { getStoredMarketplace } from '../utils/marketplace'

export type XlIntakeStatus = 'scanning' | 'saved' | 'applied' | 'completed'

export type XlIntakeLine = {
  barcode: string
  quantity: number
  applied_quantity?: number
  sort_order: number
}

export type XlIntakeUnmatched = {
  barcode: string
  quantity: number
}

export type XlIntakeSession = {
  id: number
  status: XlIntakeStatus
  seller_id: number
  seller_name: string
  has_wb_token: boolean
  unique_count: number
  total_quantity: number
  last_barcode: string
  last_sort_order: number
  last_quantity: number
  lines: XlIntakeLine[]
  unmatched: XlIntakeUnmatched[]
  warehouse_sync_warning: string
  created_at: string
  saved_at: string | null
  applied_at: string | null
  completed_at: string | null
  can_scan?: boolean
  created_products?: number
  updated_products?: number
  created_cells?: string[]
  unmatched_count?: number
  matched_count?: number
}

export function fetchXlSessions() {
  return apiFetch<XlIntakeSession[]>('/api/warehouse/xl-intake/sessions/')
}

export function createXlSession(payload: { company_name?: string; seller_id?: number }) {
  return apiFetch<XlIntakeSession>('/api/warehouse/xl-intake/sessions/', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function fetchXlSession(sessionId: number) {
  return apiFetch<XlIntakeSession>(`/api/warehouse/xl-intake/sessions/${sessionId}/`)
}

export function scanXlBarcode(sessionId: number, barcode: string) {
  return apiFetch<XlIntakeSession>(`/api/warehouse/xl-intake/sessions/${sessionId}/scan/`, {
    method: 'POST',
    body: JSON.stringify({ barcode }),
  })
}

export function saveXlSession(sessionId: number) {
  return apiFetch<XlIntakeSession>(`/api/warehouse/xl-intake/sessions/${sessionId}/save/`, {
    method: 'POST',
    body: JSON.stringify({}),
  })
}

export function completeXlSession(sessionId: number) {
  return apiFetch<XlIntakeSession>(`/api/warehouse/xl-intake/sessions/${sessionId}/complete/`, {
    method: 'POST',
    body: JSON.stringify({}),
  })
}

export function connectXlWb(sessionId: number, token: string) {
  return apiFetch<XlIntakeSession>(`/api/warehouse/xl-intake/sessions/${sessionId}/connect-wb/`, {
    method: 'POST',
    body: JSON.stringify({ token }),
  })
}

export async function downloadXlExcel(sessionId: number) {
  const token = getAccessToken()
  const response = await fetch(`/api/warehouse/xl-intake/sessions/${sessionId}/excel/`, {
    headers: token
      ? { Authorization: `Bearer ${token}`, 'X-Marketplace': getStoredMarketplace() }
      : { 'X-Marketplace': getStoredMarketplace() },
  })
  if (!response.ok) {
    let detail = `Ошибка ${response.status}`
    try {
      const data = await response.json()
      if (data.detail) detail = String(data.detail)
    } catch {
      // ignore
    }
    throw new Error(detail)
  }
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `priemka-xl-${sessionId}.xlsx`
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}
