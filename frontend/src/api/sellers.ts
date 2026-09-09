import { apiFetch } from './client'

export interface SellerWarehouse {
  id: number
  wb_warehouse_id: number
  name: string
  address: string
  office_id: number | null
  is_enabled: boolean
  synced_at: string | null
}

export function fetchSellerWarehouses(sellerId: number) {
  return apiFetch<SellerWarehouse[]>(`/api/sellers/${sellerId}/warehouses/`)
}

export function syncSellerWarehouses(sellerId: number) {
  return apiFetch<{ success: boolean; warehouses: SellerWarehouse[]; total: number }>(
    `/api/sellers/${sellerId}/warehouses/sync/`,
    { method: 'POST', body: '{}' },
  )
}

export function deleteSellerWarehouse(sellerId: number, warehouseId: number) {
  return apiFetch<{ success: boolean; detail: string }>(
    `/api/sellers/${sellerId}/warehouses/${warehouseId}/`,
    { method: 'DELETE' },
  )
}

export type ResetWarehouseStocksResult = {
  success: boolean
  message: string
  wb_barcodes_zeroed: number
  wb_units_before: number
  crm_rows_zeroed: number
  products_recalculated: number
  warehouses: Array<{
    warehouse_id: number
    warehouse_name: string
    wb_warehouse_id: number
    wb_barcodes_zeroed: number
    wb_units_before: number
  }>
}

export function resetSellerWarehouseStocks(sellerId: number, warehouseIds: number[]) {
  return apiFetch<ResetWarehouseStocksResult>(
    `/api/sellers/${sellerId}/warehouses/reset-stocks/`,
    {
      method: 'POST',
      body: JSON.stringify({ warehouse_ids: warehouseIds }),
    },
  )
}

export function toggleSellerWarehouse(sellerId: number, warehouseId: number, isEnabled: boolean) {
  return apiFetch<{ success: boolean; warehouse: SellerWarehouse }>(
    `/api/sellers/${sellerId}/warehouses/${warehouseId}/`,
    {
      method: 'PATCH',
      body: JSON.stringify({ is_enabled: isEnabled }),
    },
  )
}

export interface SellerOzonWarehouse {
  id: number
  ozon_warehouse_id: number
  name: string
  is_rfbs: boolean
  is_enabled: boolean
  synced_at: string | null
}

export function fetchSellerOzonWarehouses(sellerId: number) {
  return apiFetch<SellerOzonWarehouse[]>(`/api/sellers/${sellerId}/ozon-warehouses/`)
}

export function syncSellerOzonWarehouses(sellerId: number) {
  return apiFetch<{ success: boolean; warehouses: SellerOzonWarehouse[]; total: number }>(
    `/api/sellers/${sellerId}/ozon-warehouses/sync/`,
    { method: 'POST', body: '{}' },
  )
}

export function toggleSellerOzonWarehouse(sellerId: number, warehouseId: number, isEnabled: boolean) {
  return apiFetch<{ success: boolean; warehouse: SellerOzonWarehouse }>(
    `/api/sellers/${sellerId}/ozon-warehouses/${warehouseId}/`,
    {
      method: 'PATCH',
      body: JSON.stringify({ is_enabled: isEnabled }),
    },
  )
}

export function deleteSellerOzonWarehouse(sellerId: number, warehouseId: number) {
  return apiFetch<{ success: boolean; detail: string }>(
    `/api/sellers/${sellerId}/ozon-warehouses/${warehouseId}/`,
    { method: 'DELETE' },
  )
}

export type ExcludedSellerWarehouse = {
  id: number
  marketplace: 'wb' | 'ozon' | string
  warehouse_external_id: number
  name: string
  excluded_at: string | null
}

export function fetchExcludedSellerWarehouses(sellerId: number) {
  return apiFetch<ExcludedSellerWarehouse[]>(`/api/sellers/${sellerId}/warehouses/excluded/`)
}

export function restoreSellerWarehouse(
  sellerId: number,
  payload: { marketplace: 'wb' | 'ozon'; warehouse_external_id: number },
) {
  return apiFetch<{
    success: boolean
    detail: string
    restored: boolean
    warehouses: SellerWarehouse[]
    ozon_warehouses: SellerOzonWarehouse[]
    excluded: ExcludedSellerWarehouse[]
  }>(`/api/sellers/${sellerId}/warehouses/restore/`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}
