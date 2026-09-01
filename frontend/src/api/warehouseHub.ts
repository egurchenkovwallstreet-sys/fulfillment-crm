import { apiFetch } from './client'
import type { Seller } from './warehouse'

export type OnboardingWarehouse = {
  id: number
  wb_warehouse_id?: number
  ozon_warehouse_id?: number
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
  marketplace?: string
  catalog_mode?: 'all' | 'with_stock'
  next_cell_number?: number
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
  skipped_unknown_details: Array<{ barcode: string; add_quantity: number }>
  totals: {
    file_barcodes: number
    file_units: number
    to_apply: number
    skipped_unknown: number
    skipped_units: number
    new_products: number
    add_units: number
  }
}

export type StockImportMismatch = {
  barcode: string
  add_quantity: number
  crm_before: number
  crm_expected: number
  crm_actual: number
  wb_before: number
  wb_expected: number
  wb_actual: number
  error: string
  stage: string
}

export type StockImportSummary = {
  file_barcodes: number
  file_units: number
  was_crm_units: number
  was_wb_units: number
  added_units: number
  expected_crm_units: number
  expected_wb_units: number
  result_crm_units: number
  result_wb_units: number
  applied_barcodes: number
  verified_barcodes: number
  failed_barcodes: number
}

export type StockImportResult = {
  success: boolean
  ok: boolean
  applied: number
  created_products: number
  verified: number
  skipped_unknown: string[]
  skipped_unknown_details: Array<{ barcode: string; add_quantity: number }>
  mismatches: StockImportMismatch[]
  summary: StockImportSummary
  add_units: number
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

export type StockTransferWarehouseDelta = {
  name: string
  before: number
  after: number
}

export type StockTransferResultItem = {
  barcode: string
  quantity_requested: number
  quantity_moved: number
  total_before: number
  total_after: number
  from_warehouse: StockTransferWarehouseDelta
  to_warehouse: StockTransferWarehouseDelta
  ok: boolean
}

export type StockTransferSingleResult = {
  success: boolean
  ok: boolean
  item: StockTransferResultItem
}

export type StockTransferBulkResult = {
  success: boolean
  ok: boolean
  transferred: number
  skipped: number
  requested_count: number
  errors: Array<{ product_id: number; barcode: string; error: string }>
  items: StockTransferResultItem[]
  from_warehouse_name?: string
  to_warehouse_name?: string
}

export type StockTransferResultView = {
  ok: boolean
  summary: string
  items: StockTransferResultItem[]
  errors: Array<{ barcode: string; error: string }>
}

export function buildTransferResultView(
  payload: StockTransferSingleResult | StockTransferBulkResult,
  *,
  fromName: string,
  toName: string,
): StockTransferResultView {
  if ('item' in payload) {
    const item = payload.item
    return {
      ok: payload.ok,
      summary: payload.ok
        ? `Все ${item.quantity_moved} шт. перенесены «${fromName}» → «${toName}». Итого по баркоду без изменений.`
        : `Перенос выполнен, но остатки не совпали с ожиданием. Проверьте таблицу ниже.`,
      items: [item],
      errors: [],
    }
  }

  const bulk = payload
  const parts: string[] = []
  parts.push(`Перенесено: ${bulk.transferred} из ${bulk.requested_count}`)
  if (bulk.skipped > 0) {
    parts.push(`пропущено (0 на «${fromName}»): ${bulk.skipped}`)
  }
  if (bulk.errors.length > 0) {
    parts.push(`ошибок: ${bulk.errors.length}`)
  }
  if (bulk.ok) {
    parts.push('все остатки перенесены, сумма по баркодам сохранена')
  } else if (bulk.transferred > 0) {
    parts.push('есть позиции с расхождениями или ошибками')
  } else {
    parts.push('ничего не перенесено')
  }

  return {
    ok: bulk.ok,
    summary: parts.join(' · '),
    items: bulk.items,
    errors: bulk.errors.map((row) => ({ barcode: row.barcode, error: row.error })),
  }
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
  return apiFetch<StockTransferSingleResult>(`/api/warehouse/sellers/${sellerId}/stock-transfer/`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function transferStockBulk(
  sellerId: number,
  payload: {
    from_warehouse_id: number
    to_warehouse_id: number
    product_ids?: number[]
  },
) {
  return apiFetch<StockTransferBulkResult>(
    `/api/warehouse/sellers/${sellerId}/stock-transfer-bulk/`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
  )
}

export type StockDistributeResult = {
  success: boolean
  distributed: number
  skipped: number
  errors: Array<{ product_id: number; barcode: string; error: string }>
}

export function distributeStockEvenly(sellerId: number, productIds?: number[]) {
  return apiFetch<StockDistributeResult>(
    `/api/warehouse/sellers/${sellerId}/stock-distribute/`,
    {
      method: 'POST',
      body: JSON.stringify(
        productIds && productIds.length > 0 ? { product_ids: productIds } : {},
      ),
    },
  )
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
  return apiFetch<StockImportResult>(`/api/warehouse/stock-import/${sellerId}/apply/`, {
    method: 'POST',
    body: JSON.stringify({ warehouse_id: warehouseId, rows }),
  })
}

export function pushOzonStocks(sellerId: number, warehouseId: number) {
  return apiFetch<{
    success: boolean
    message: string
    sent: number
    updated: number
    skipped: number
    error_count: number
    errors: Array<{ offer_id: string; error: string }>
    warehouse_name: string
  }>(`/api/warehouse/sellers/${sellerId}/ozon-stocks/`, {
    method: 'POST',
    body: JSON.stringify({ warehouse_id: warehouseId }),
  })
}

export type { Seller }
