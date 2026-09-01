import { apiFetch } from './client'

export interface Order {
  id: number
  wb_order_id: number
  barcode: string
  seller: number
  seller_name: string
  cell_number: string
  status: string
  status_display: string
  marking_bound: boolean
  created_at: string
}

export interface OrderStats {
  orders_today: number
  in_picking: number
  new_orders: number
  in_assembly?: number
  in_delivery?: number
  sellers_count?: number
  off_crm_pending_count?: number
  sku_count: number
  stats_source?: 'cache' | 'database'
  counts_synced_at?: string | null
}

export interface DashboardStats {
  new_orders: number
  in_assembly: number
  in_delivery: number
}

export interface PickListItem {
  id: number
  cell_number: string
  barcode: string
  product_name: string
  wb_nm_id?: number | null
  wb_article?: string
  tech_size?: string
  quantity: number
  picked_quantity: number
}

export interface PickList {
  id: number
  seller: number
  seller_name: string
  is_completed: boolean
  created_at: string
  items: PickListItem[]
  items_count: number
  total_quantity: number
}

export interface PickListBrief {
  id: number
  seller: number
  seller_name: string
  is_completed: boolean
  created_at: string
  items_count: number
}

export interface SyncResult {
  success: boolean
  created?: number
  updated?: number
  without_product?: number
  fetched?: number
  raw_total?: number
  skipped_no_barcode?: number
  pages?: number
  statuses_fetched?: number
  statuses_updated?: number
  reconciled?: number
  sync_version?: string
  status_error?: string
  wb_counts?: { new?: number; in_picking?: number; in_delivery?: number }
  live_counts?: { new?: number; in_picking?: number; in_delivery?: number }
  delivery_all?: number
  delivery_recent?: number
  delivery_breakdown?: Record<string, number>
  reconcile?: {
    cancelled_terminal?: number
    shipped_delivered?: number
    shipped_not_waiting?: number
    shipped_missing?: number
    delivery_status_breakdown?: Record<string, number>
  }
  results?: SyncResult[]
  errors?: { seller_id: number; error: string }[]
  dashboard_stats?: DashboardStats
}

export function fetchOrders(params?: { seller_id?: number; status?: string }) {
  const search = new URLSearchParams()
  if (params?.seller_id) search.set('seller_id', String(params.seller_id))
  if (params?.status) search.set('status', params.status)
  const qs = search.toString()
  return apiFetch<Order[]>(`/api/orders/${qs ? `?${qs}` : ''}`)
}

export function fetchOrderStats() {
  return apiFetch<OrderStats>('/api/orders/stats/')
}

export function syncOrders(sellerId?: number, mode: 'full' | 'quick' = 'full') {
  const body: { seller_id?: number; mode: 'full' | 'quick' } = { mode }
  if (sellerId) body.seller_id = sellerId
  return apiFetch<SyncResult>('/api/orders/sync/', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function fetchPickLists(sellerId?: number) {
  const qs = sellerId ? `?seller_id=${sellerId}` : ''
  return apiFetch<PickListBrief[]>(`/api/orders/pick-lists/${qs}`)
}

export function fetchPickList(id: number) {
  return apiFetch<PickList>(`/api/orders/pick-lists/${id}/`)
}

export function generatePickList(
  sellerId: number,
  options?: { force?: boolean; stage?: 'new' | 'confirm' },
) {
  return apiFetch<PickList>('/api/orders/pick-lists/generate/', {
    method: 'POST',
    body: JSON.stringify({
      seller_id: sellerId,
      force: Boolean(options?.force),
      stage: options?.stage || 'new',
    }),
  })
}
