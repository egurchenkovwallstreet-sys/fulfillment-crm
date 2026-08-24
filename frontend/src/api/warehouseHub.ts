import { apiFetch } from './client'
import type { Seller } from './warehouse'

export type OnboardingWarehouse = {
  id: number
  wb_warehouse_id: number
  name: string
  is_enabled: boolean
}

export type OnboardingItem = {
  barcode: string
  wb_nm_id: number
  vendor_code: string
  title: string
  tech_size: string
  wb_size: string
  size_label: string
  photo_url: string
  requires_marking: boolean
  wb_stock_total: number
  wb_stock_by_warehouse: Record<string, number>
  cell_number: string
  already_in_crm: boolean
  excluded: boolean
}

export type OnboardingArticle = {
  wb_nm_id: number
  vendor_code: string
  title: string
  photo_url: string
  requires_marking: boolean
  items: OnboardingItem[]
}

export type OnboardingPreview = {
  success: boolean
  seller_id: number
  catalog_mode?: 'all' | 'with_stock'
  cards_count: number
  barcodes_count: number
  new_barcodes_count: number
  existing_barcodes_count: number
  filtered_articles_count?: number
  warehouses: OnboardingWarehouse[]
  articles: OnboardingArticle[]
  items: OnboardingItem[]
}

export type StockImportPreviewRow = {
  barcode: string
  add_quantity: number
  status: string
  title: string
  crm_before: number
  crm_after: number
  wb_before: number
  wb_after: number
  will_create: boolean
  cell_number: string
  message: string
}

export type StockImportPreview = {
  success: boolean
  warehouse: { id: number; wb_warehouse_id: number; name: string }
  rows: StockImportPreviewRow[]
  skipped_unknown: string[]
  totals: {
    file_rows: number
    to_apply: number
    skipped_unknown: number
    new_products: number
    add_units: number
  }
}

export type StockWarehouseMeta = {
  id: number
  wb_warehouse_id: number
  name: string
}

export type StockWarehouseQty = {
  warehouse_id: number
  quantity: number
}

export type StockOverviewProduct = {
  product_id: number
  barcode: string
  name: string
  cell_number: string
  photo_url: string
  wb_size: string
  tech_size: string
  crm_quantity: number
  wb_total: number
  by_warehouse: StockWarehouseQty[]
}

export type StockOverview = {
  success: boolean
  products: StockOverviewProduct[]
  warehouses: StockWarehouseMeta[]
}

export function fetchOnboardingPreview(
  sellerId: number,
  payload: { catalog_mode: 'all' | 'with_stock'; warehouse_ids: number[] },
) {
  return apiFetch<OnboardingPreview>(`/api/warehouse/onboarding/${sellerId}/preview/`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function applyOnboardingExclusions(
  sellerId: number,
  items: OnboardingItem[],
  excludeBarcodes: string[],
  excludeNmIds: number[],
) {
  return apiFetch<{ success: boolean; items: OnboardingItem[] }>(
    `/api/warehouse/onboarding/${sellerId}/exclude/`,
    {
      method: 'POST',
      body: JSON.stringify({
        items,
        exclude_barcodes: excludeBarcodes,
        exclude_nm_ids: excludeNmIds,
      }),
    },
  )
}

export function confirmOnboarding(sellerId: number, items: OnboardingItem[]) {
  return apiFetch<{ success: boolean; created_products: number; skipped: number }>(
    `/api/warehouse/onboarding/${sellerId}/confirm/`,
    {
      method: 'POST',
      body: JSON.stringify({ items }),
    },
  )
}

export function fetchStockOverview(sellerId: number) {
  return apiFetch<StockOverview>(`/api/warehouse/sellers/${sellerId}/stock-overview/`)
}

export function transferStock(
  sellerId: number,
  payload: {
    product_id: number
    from_warehouse_id: number
    to_warehouse_id: number
    quantity: number
  },
) {
  return apiFetch(`/api/warehouse/sellers/${sellerId}/stock-transfer/`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function previewStockImport(
  sellerId: number,
  warehouseId: number,
  file: File,
): Promise<StockImportPreview> {
  const form = new FormData()
  form.append('file', file)
  form.append('warehouse_id', String(warehouseId))

  const headers = new Headers()
  const token = (await import('./tokens')).getAccessToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)

  const response = await fetch(`/api/warehouse/stock-import/${sellerId}/preview/`, {
    method: 'POST',
    headers,
    body: form,
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
  return response.json() as Promise<StockImportPreview>
}

export function applyStockImport(
  sellerId: number,
  warehouseId: number,
  rows: StockImportPreviewRow[],
) {
  return apiFetch<{
    success: boolean
    applied: number
    created_products: number
    skipped_unknown: string[]
    errors: Array<{ barcode: string; error: string }>
    add_units: number
  }>(`/api/warehouse/stock-import/${sellerId}/apply/`, {
    method: 'POST',
    body: JSON.stringify({ warehouse_id: warehouseId, rows }),
  })
}

export type { Seller }
