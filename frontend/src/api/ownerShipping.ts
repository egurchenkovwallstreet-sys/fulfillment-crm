import { apiFetch } from './client'
import type { ShippingPoint } from './assembly'

export type OwnerShippingPoint = ShippingPoint & {
  zone_label?: string
  is_pinned?: boolean
}

export type OwnerShippingPointsResult = {
  success: boolean
  city: string
  scope: string
  cargo_type: number
  fulfillment_id: number
  reference_seller_id: number
  reference_seller_name: string
  from_cache: boolean
  cached_at: string | null
  cache_ttl_sec: number
  shipping_points: OwnerShippingPoint[]
  shipping_points_sc: OwnerShippingPoint[]
  shipping_points_pp: OwnerShippingPoint[]
}

export function fetchOwnerShippingPoints(options?: { refresh?: boolean; sellerId?: number }) {
  const qs = new URLSearchParams()
  if (options?.refresh) qs.set('refresh', '1')
  if (options?.sellerId) qs.set('seller_id', String(options.sellerId))
  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  return apiFetch<OwnerShippingPointsResult>(`/api/orders/owner/shipping-points/${suffix}`)
}
