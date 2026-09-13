import { apiFetch } from './client'
import { getAccessToken } from './tokens'
import { getStoredMarketplace } from '../utils/marketplace'

export type XlListStatus = 'active' | 'completed'

export type XlListLine = {
  barcode: string
  quantity: number
  sort_order: number
}

export type XlListSession = {
  id: number
  title: string
  status: XlListStatus
  unique_count: number
  total_quantity: number
  last_barcode: string
  last_sort_order: number
  last_quantity: number
  lines: XlListLine[]
  created_at: string
  completed_at: string | null
  can_edit?: boolean
}

export function fetchXlListSessions() {
  return apiFetch<XlListSession[]>('/api/warehouse/xl-list/sessions/')
}

export function createXlListSession(payload: { title?: string }) {
  return apiFetch<XlListSession>('/api/warehouse/xl-list/sessions/', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function fetchXlListSession(sessionId: number) {
  return apiFetch<XlListSession>(`/api/warehouse/xl-list/sessions/${sessionId}/`)
}

export function scanXlListBarcode(sessionId: number, barcode: string) {
  return apiFetch<XlListSession>(`/api/warehouse/xl-list/sessions/${sessionId}/scan/`, {
    method: 'POST',
    body: JSON.stringify({ barcode }),
  })
}

export function addXlListLine(sessionId: number, barcode: string, quantity: number) {
  return apiFetch<XlListSession>(`/api/warehouse/xl-list/sessions/${sessionId}/add-line/`, {
    method: 'POST',
    body: JSON.stringify({ barcode, quantity }),
  })
}

export function updateXlListLine(sessionId: number, barcode: string, quantity: number) {
  return apiFetch<XlListSession>(`/api/warehouse/xl-list/sessions/${sessionId}/update-line/`, {
    method: 'POST',
    body: JSON.stringify({ barcode, quantity }),
  })
}

export function deleteXlListLine(sessionId: number, barcode: string) {
  return apiFetch<XlListSession>(`/api/warehouse/xl-list/sessions/${sessionId}/delete-line/`, {
    method: 'POST',
    body: JSON.stringify({ barcode }),
  })
}

export function completeXlListSession(sessionId: number) {
  return apiFetch<XlListSession>(`/api/warehouse/xl-list/sessions/${sessionId}/complete/`, {
    method: 'POST',
    body: JSON.stringify({}),
  })
}

export async function downloadXlListExcel(sessionId: number) {
  const token = getAccessToken()
  const response = await fetch(`/api/warehouse/xl-list/sessions/${sessionId}/excel/`, {
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
  link.download = `barcodes-xl-list-${sessionId}.xlsx`
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}
