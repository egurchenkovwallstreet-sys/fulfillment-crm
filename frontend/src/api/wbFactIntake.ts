import { apiFetch } from './client'
import type { CellLabelData } from './warehouse'

export type WbFactIntakeStatus = 'scanning' | 'completed'

export type WbFactIntakeLine = {
  id: number
  barcode: string
  wb_nm_id?: number | null
  vendor_code: string
  title: string
  tech_size: string
  wb_size: string
  size_label: string
  photo_url: string
  color_label: string
  requires_marking: boolean
  wb_stock_snapshot: number
  accepted: boolean
  fact_quantity: number
  cell_number: string
  product_id?: number | null
  wb_stock?: number
  new_orders?: number
  picking_orders?: number
  expected?: number
  wb_target?: number
  color?: 'green' | 'yellow' | 'red'
}

export type WbFactIntakeReport = {
  green: WbFactIntakeLine[]
  yellow: WbFactIntakeLine[]
  red: WbFactIntakeLine[]
  green_count: number
  yellow_count: number
  red_count: number
}

export type WbFactIntakeSession = {
  id: number
  status: WbFactIntakeStatus
  seller_id: number
  seller_name: string
  warehouse_id: number
  warehouse_name: string
  wb_warehouse_id: number
  marketplace: string
  catalog_count: number
  accepted_count: number
  can_edit: boolean
  wb_pushed_at: string | null
  created_at: string | null
  completed_at: string | null
  accepted?: WbFactIntakeLine[]
  report?: WbFactIntakeReport | null
  pushed?: number
}

export type WbFactIntakeScanResult = {
  session: WbFactIntakeSession
  line: WbFactIntakeLine
  created_cell: boolean
  cell_label: CellLabelData | null
}

export function fetchWbFactIntakeSessions() {
  return apiFetch<WbFactIntakeSession[]>('/api/warehouse/wb-fact-intake/sessions/')
}

export function createWbFactIntakeSession(payload: {
  seller_id?: number
  company_name?: string
  warehouse_id: number
}) {
  return apiFetch<WbFactIntakeSession>('/api/warehouse/wb-fact-intake/sessions/', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function fetchWbFactIntakeSession(sessionId: number) {
  return apiFetch<WbFactIntakeSession>(`/api/warehouse/wb-fact-intake/sessions/${sessionId}/`)
}

export function deleteWbFactIntakeSession(sessionId: number) {
  return apiFetch<{ deleted: boolean; id: number }>(
    `/api/warehouse/wb-fact-intake/sessions/${sessionId}/`,
    { method: 'DELETE' },
  )
}

export function scanWbFactIntake(
  sessionId: number,
  barcode: string,
  options?: { scan_mode?: 'piece' | 'set'; quantity?: number },
) {
  return apiFetch<WbFactIntakeScanResult>(`/api/warehouse/wb-fact-intake/sessions/${sessionId}/scan/`, {
    method: 'POST',
    body: JSON.stringify({
      barcode,
      scan_mode: options?.scan_mode || 'piece',
      quantity: options?.quantity ?? 0,
    }),
  })
}

export function setWbFactIntakeQty(sessionId: number, barcode: string, quantity: number) {
  return apiFetch<WbFactIntakeScanResult>(
    `/api/warehouse/wb-fact-intake/sessions/${sessionId}/set-qty/`,
    {
      method: 'POST',
      body: JSON.stringify({ barcode, quantity }),
    },
  )
}

export function fetchWbFactIntakeReport(sessionId: number) {
  return apiFetch<WbFactIntakeSession>(`/api/warehouse/wb-fact-intake/sessions/${sessionId}/report/`)
}

export function finishWbFactIntake(sessionId: number) {
  return apiFetch<WbFactIntakeSession>(`/api/warehouse/wb-fact-intake/sessions/${sessionId}/finish/`, {
    method: 'POST',
    body: '{}',
  })
}
