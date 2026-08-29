import { apiFetch } from './client'

export type ArticleIntakeStatus = 'active' | 'completed'

export type ArticleIntakeProduct = {
  id: number
  barcode: string
  name: string
  quantity: number
  cell_number: string
  tech_size: string
  color_label: string
  article_group_key: string
}

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
  active_group_key: string
  marketplace_pushed_at: string | null
  created_at: string
  completed_at: string | null
  can_scan?: boolean
  can_edit?: boolean
  can_push?: boolean
  products?: ArticleIntakeProduct[]
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
  article_label: string
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
  article_label: string
  vendor_code: string
  title: string
  color_label: string
  group_size?: number
  photo_url: string
  scanned_barcode: string
  scanned_quantity: number
  next_cell_number?: number
  items: ArticleGroupPreviewItem[]
}

export type ArticleScanAdded = {
  action: 'added'
  product: ArticleIntakeProduct
  quantity_added: number
  session: ArticleIntakeSession
}

export type ArticleScanPreview = {
  action: 'preview'
  preview: ArticleGroupPreview
  session: ArticleIntakeSession
}

export type ArticleScanKnown = {
  action: 'known'
  product: ArticleIntakeProduct
  session: ArticleIntakeSession
}

export type ArticleScanIncremented = {
  action: 'incremented'
  product: ArticleIntakeProduct
  quantity_added: number
  session: ArticleIntakeSession
}

export type ArticleScanResult =
  | ArticleScanAdded
  | ArticleScanPreview
  | ArticleScanKnown
  | ArticleScanIncremented

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

export function scanArticleIntake(
  sessionId: number,
  barcode: string,
  options?: { quantity?: number; scan_mode?: 'lookup' | 'increment' },
) {
  return apiFetch<ArticleScanResult>(`/api/warehouse/article-intake/sessions/${sessionId}/scan/`, {
    method: 'POST',
    body: JSON.stringify({
      barcode,
      quantity: options?.quantity ?? 0,
      scan_mode: options?.scan_mode ?? 'lookup',
    }),
  })
}

export function incrementArticleIntake(sessionId: number, barcode: string) {
  return apiFetch<ArticleScanIncremented>(
    `/api/warehouse/article-intake/sessions/${sessionId}/increment/`,
    {
      method: 'POST',
      body: JSON.stringify({ barcode }),
    },
  )
}

export function confirmArticleGroup(
  sessionId: number,
  payload: {
    scanned_barcode: string
    items: Array<{ barcode: string; cell_number: string; excluded?: boolean }>
  },
) {
  return apiFetch<{
    group_key: string
    created_products: number
    created_cells: string[]
    products: ArticleIntakeProduct[]
    session: ArticleIntakeSession
  }>(`/api/warehouse/article-intake/sessions/${sessionId}/confirm-group/`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function saveArticleGroupQuantities(
  sessionId: number,
  groupKey: string,
  items: Array<{ barcode: string; quantity: number }>,
) {
  return apiFetch<{ updated: number; group_key: string; session: ArticleIntakeSession }>(
    `/api/warehouse/article-intake/sessions/${sessionId}/save-quantities/`,
    {
      method: 'POST',
      body: JSON.stringify({ group_key: groupKey, items }),
    },
  )
}

export function deleteArticleIntakeProduct(sessionId: number, productId: number) {
  return apiFetch<{ deleted: boolean; session: ArticleIntakeSession }>(
    `/api/warehouse/article-intake/sessions/${sessionId}/delete-product/`,
    {
      method: 'POST',
      body: JSON.stringify({ product_id: productId }),
    },
  )
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
    locked: boolean
    message: string
    session: ArticleIntakeSession
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
