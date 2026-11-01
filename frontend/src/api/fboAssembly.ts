import { apiFetch } from './client'
import { getAccessToken } from './tokens'
import { getStoredMarketplace } from '../utils/marketplace'

export type FboBoxLabel = {
  seller_name: string
  box_number: string
  date: string
  box_id: number
}

export type FboAssemblyLine = {
  id: number
  barcode: string
  quantity: number
}

export type FboAssemblyBox = {
  id: number
  box_number: string
  status: 'open' | 'closed'
  sort_order: number
  closed_at: string | null
  total_units: number | null
  lines?: FboAssemblyLine[]
  label: FboBoxLabel
}

export type FboAssemblySession = {
  id: number
  seller_id: number
  seller_name: string
  status: 'active' | 'paused' | 'completed'
  marketplace: string
  created_at: string
  completed_at: string | null
  stocks_finalized_at: string | null
  can_finalize_stocks: boolean
  box_count: number
  total_units: number
  open_box_id: number | null
  open_box_number: string
  boxes: FboAssemblyBox[]
}

export type FboFinalizeLineReport = {
  barcode: string
  crm_was: number
  fbo_qty: number
  wb_new_orders: number
  wb_picking_orders: number
  wb_reserved_total: number
  crm_after: number
  wb_total_before: number
  wb_total_after: number
  check_crm: boolean
  check_wb: boolean
  warehouses: Array<{
    warehouse_name: string
    before: number
    after: number
    changed: boolean
  }>
}

export type FboFinalizeReport = {
  session_id: number
  finalized_at: string
  lines: FboFinalizeLineReport[]
}

export type FboScanResponse = FboAssemblySession & {
  last_scan?: {
    barcode: string
    quantity_in_box: number
  }
  closed_box_label?: FboBoxLabel
}

export function fetchFboSessions() {
  return apiFetch<FboAssemblySession[]>('/api/warehouse/fbo-assembly/sessions/')
}

export function createFboSession(sellerId: number) {
  return apiFetch<FboAssemblySession>('/api/warehouse/fbo-assembly/sessions/', {
    method: 'POST',
    body: JSON.stringify({ seller_id: sellerId }),
  })
}

export function fetchFboSession(sessionId: number) {
  return apiFetch<FboAssemblySession>(`/api/warehouse/fbo-assembly/sessions/${sessionId}/`)
}

export function pauseFboSession(sessionId: number) {
  return apiFetch<FboAssemblySession>(`/api/warehouse/fbo-assembly/sessions/${sessionId}/pause/`, {
    method: 'POST',
  })
}

export function resumeFboSession(sessionId: number) {
  return apiFetch<FboAssemblySession>(`/api/warehouse/fbo-assembly/sessions/${sessionId}/resume/`, {
    method: 'POST',
  })
}

export function completeFboSession(sessionId: number) {
  return apiFetch<FboAssemblySession>(`/api/warehouse/fbo-assembly/sessions/${sessionId}/complete/`, {
    method: 'POST',
  })
}

export function createFboBox(sessionId: number, boxNumber: string) {
  return apiFetch<FboScanResponse>(`/api/warehouse/fbo-assembly/sessions/${sessionId}/boxes/`, {
    method: 'POST',
    body: JSON.stringify({ box_number: boxNumber }),
  })
}

export function closeFboBox(sessionId: number, boxId: number) {
  return apiFetch<FboScanResponse>(
    `/api/warehouse/fbo-assembly/sessions/${sessionId}/boxes/${boxId}/close/`,
    { method: 'POST' },
  )
}

export function scanFboBarcode(sessionId: number, boxId: number, barcode: string) {
  return apiFetch<FboScanResponse>(
    `/api/warehouse/fbo-assembly/sessions/${sessionId}/boxes/${boxId}/scan/`,
    {
      method: 'POST',
      body: JSON.stringify({ barcode }),
    },
  )
}

export function finalizeFboStocks(sessionId: number) {
  return apiFetch<{ session: FboAssemblySession; report: FboFinalizeReport }>(
    `/api/warehouse/fbo-assembly/sessions/${sessionId}/finalize-stocks/`,
    { method: 'POST' },
  )
}

export async function downloadFboExcel(sessionId: number) {
  const token = getAccessToken()
  const response = await fetch(`/api/warehouse/fbo-assembly/sessions/${sessionId}/excel/`, {
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
  link.download = `fbo-assembly-${sessionId}.xlsx`
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}
