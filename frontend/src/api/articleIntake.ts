import { apiFetch } from './client'

export type ArticleIntakeStatus = 'active' | 'completed'

export type ArticleIntakeSession = {
  id: number
  status: ArticleIntakeStatus
  seller_id: number
  seller_name: string
  marketplace: string
  scan_count: number
  total_units: number
  confirmed_groups_count: number
  products_count: number
  created_at: string
  completed_at: string | null
  can_scan?: boolean
}

export type ArticleGroupPreviewItem = {
  barcode: string
  wb_nm_id: number
  vendor_code: string
  title: string
  tech_size: string
  wb_size: string
  size_label: string
  color_label: string
  photo_url: string
  requires_marking: boolean
  cell_number: string
  quantity: number
  already_in_crm: boolean
  excluded: boolean
}

export type ArticleGroupPreview = {
  group_key: string
  article_id: number
  vendor_code: string
  title: string
  color_label: string
  photo_url: string
  scanned_barcode: string
  scanned_quantity: number
  next_cell_number?: number
  items: ArticleGroupPreviewItem[]
}

export type ArticleScanAdded = {
  action: 'added'
  product: {
    id: number
    barcode: string
    name: string
    quantity: number
    cell_number: string
    tech_size: string
    color_label: string
    article_group_key: string
  }
  quantity_added: number
  session: ArticleIntakeSession
}

export type ArticleScanPreview = {
  action: 'preview'
  preview: ArticleGroupPreview
  session: ArticleIntakeSession
}

export type ArticleScanResult = ArticleScanAdded | ArticleScanPreview

export function fetchArticleIntakeSessions() {
  return apiFetch<ArticleIntakeSession[]>('/api/warehouse/article-intake/sessions/')
}

export function createArticleIntakeSession(payload: { company_name?: string; seller_id?: number }) {
  return apiFetch<ArticleIntakeSession>('/api/warehouse/article-intake/sessions/', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function fetchArticleIntakeSession(sessionId: number) {
  return apiFetch<ArticleIntakeSession>(`/api/warehouse/article-intake/sessions/${sessionId}/`)
}

export function scanArticleIntake(sessionId: number, barcode: string, quantity: number) {
  return apiFetch<ArticleScanResult>(`/api/warehouse/article-intake/sessions/${sessionId}/scan/`, {
    method: 'POST',
    body: JSON.stringify({ barcode, quantity }),
  })
}

export function confirmArticleGroup(
  sessionId: number,
  payload: {
    scanned_barcode: string
    scanned_quantity: number
    items: Array<{ barcode: string; cell_number: string; excluded?: boolean }>
  },
) {
  return apiFetch<{
    group_key: string
    created_products: number
    created_cells: string[]
    added_units: number
    session: ArticleIntakeSession
  }>(`/api/warehouse/article-intake/sessions/${sessionId}/confirm-group/`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function pushArticleIntakeToMarketplace(
  sessionId: number,
  warehouseId: number,
  mode: 'replace' | 'add',
) {
  return apiFetch<{
    updated: number
    errors: Array<{ barcode?: string; offer_id?: string; error: string }>
    error_count: number
    mode: string
    message: string
  }>(`/api/warehouse/article-intake/sessions/${sessionId}/push-marketplace/`, {
    method: 'POST',
    body: JSON.stringify({ warehouse_id: warehouseId, mode }),
  })
}

export function completeArticleIntakeSession(sessionId: number) {
  return apiFetch<ArticleIntakeSession>(
    `/api/warehouse/article-intake/sessions/${sessionId}/complete/`,
    {
      method: 'POST',
      body: JSON.stringify({}),
    },
  )
}
