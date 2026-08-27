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
