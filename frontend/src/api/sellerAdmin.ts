import { apiFetch } from './client'

import type { SellerWeeklyShipments } from './sellerCabinet'

export type SellerManageItem = {
  id: number
  company_name: string
  is_active: boolean
  has_account: boolean
  username: string | null
  invite_token: string | null
  wb_enabled: boolean
  ozon_enabled: boolean
  has_wb_token: boolean
  has_ozon_api: boolean
  ozon_client_id: string
  wb_count_new: number
  wb_count_assembly: number
  wb_count_delivery: number
  ozon_count_new: number
  ozon_count_assembly: number
  ozon_count_delivery: number
  created_at: string
}

export type SellerCreatePayload = {
  company_name: string
  is_active?: boolean
  wb_enabled?: boolean
  ozon_enabled?: boolean
  wb_token?: string
  ozon_client_id?: string
  ozon_api_key?: string
}

export type SellerUpdatePayload = {
  company_name?: string
  is_active?: boolean
  wb_enabled?: boolean
  ozon_enabled?: boolean
}

export type SellerInviteResponse = {
  token: string
  invite_path: string
  has_account: boolean
  company_name: string
}

export async function fetchSellersManage(): Promise<SellerManageItem[]> {
  return apiFetch<SellerManageItem[]>('/api/sellers/manage/')
}

export async function createSeller(payload: SellerCreatePayload): Promise<SellerManageItem & { invite_url?: string }> {
  return apiFetch('/api/sellers/manage/', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function fetchSellerInvite(sellerId: number): Promise<SellerInviteResponse> {
  return apiFetch<SellerInviteResponse>(`/api/sellers/manage/${sellerId}/invite/`, {
    method: 'POST',
  })
}

export async function updateSellerMarketplaces(
  sellerId: number,
  payload: { wb_enabled?: boolean; ozon_enabled?: boolean },
) {
  return apiFetch<SellerManageItem>(`/api/sellers/manage/${sellerId}/marketplaces/`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export async function saveSellerOzonKeys(sellerId: number, payload: { client_id: string; api_key: string }) {
  return apiFetch<{
    success: boolean
    ping_ok: boolean
    detail: string
    seller: SellerManageItem
  }>(`/api/sellers/manage/${sellerId}/ozon-keys/`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function updateSeller(
  sellerId: number,
  payload: SellerUpdatePayload,
): Promise<SellerManageItem> {
  return apiFetch<SellerManageItem>(`/api/sellers/manage/${sellerId}/`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export async function deleteSeller(sellerId: number) {
  return apiFetch<{ success: boolean; detail: string }>(`/api/sellers/manage/${sellerId}/`, {
    method: 'DELETE',
  })
}

export async function saveSellerWbToken(sellerId: number, token: string) {
  return apiFetch<{
    success: boolean
    ping_ok: boolean
    detail: string
    seller: SellerManageItem
  }>(`/api/sellers/manage/${sellerId}/wb-token/`, {
    method: 'POST',
    body: JSON.stringify({ token }),
  })
}

export async function clearSellerWbToken(sellerId: number): Promise<SellerManageItem> {
  return apiFetch<SellerManageItem>(`/api/sellers/manage/${sellerId}/wb-token/`, {
    method: 'DELETE',
  })
}

export async function clearSellerOzonKeys(sellerId: number): Promise<SellerManageItem> {
  return apiFetch<SellerManageItem>(`/api/sellers/manage/${sellerId}/ozon-keys/`, {
    method: 'DELETE',
  })
}

export async function createPriceGroup(payload: {
  name: string
  processing_price: string
  sort_order?: number
}): Promise<PriceGroupItem> {
  return apiFetch<PriceGroupItem>('/api/warehouse/price-groups/', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function updatePriceGroup(
  groupId: number,
  payload: Partial<{ name: string; processing_price: string; sort_order: number }>,
): Promise<PriceGroupItem> {
  return apiFetch<PriceGroupItem>(`/api/warehouse/price-groups/${groupId}/`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export async function deletePriceGroup(groupId: number): Promise<void> {
  await apiFetch(`/api/warehouse/price-groups/${groupId}/`, { method: 'DELETE' })
}

export type InvitePreview = {
  company_name: string
  has_account: boolean
  token: string
}

export async function fetchInvitePreview(token: string): Promise<InvitePreview> {
  return apiFetch<InvitePreview>(`/api/auth/invite/${token}/`)
}

export type RegisterPayload = {
  token: string
  username: string
  password: string
  email?: string
}

export async function registerSeller(payload: RegisterPayload) {
  return apiFetch<{
    access: string
    refresh: string
    user: import('../types/auth').User
  }>('/api/auth/register/', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export type PriceGroupItem = {
  id: number
  name: string
  processing_price: string
  sort_order: number
}

export type SellerPricingGroup = {
  id: number
  name: string
  default_price: string
  product_count: number
  tariff: string | null
  mixed_tariffs: boolean
}

export type SellerPricingSummary = {
  seller_id: number
  company_name: string
  product_count: number
  ungrouped_count: number
  common_tariff: string | null
  mixed_common_tariff: boolean
  groups: SellerPricingGroup[]
  liter?: SellerLiterTariffs
}

export type SellerLiterTariffs = {
  pricing_mode: 'per_unit' | 'per_liter'
  first_liter_shipment_price: string
  next_liter_shipment_price: string
  marking_surcharge_per_unit: string
  storage_tariff_per_liter_month: string
}

export type SellerLiterTariffApplyPayload = {
  pricing_mode: 'per_unit' | 'per_liter'
  first_liter_shipment_price?: string
  next_liter_shipment_price?: string
  marking_surcharge_per_unit?: string
  storage_tariff_per_liter_month?: string
}

export type SellerTariffApplyPayload = {
  scope: 'all' | 'group'
  price: string
  price_group_id?: number
  assign_group?: boolean
  storage_tariff_per_liter_month?: string
}

export async function fetchPriceGroups(): Promise<PriceGroupItem[]> {
  return apiFetch<PriceGroupItem[]>('/api/warehouse/price-groups/')
}

export async function fetchSellerPricing(sellerId: number): Promise<SellerPricingSummary> {
  return apiFetch<SellerPricingSummary>(`/api/warehouse/sellers/${sellerId}/pricing/`)
}

export async function applySellerLiterTariff(
  sellerId: number,
  payload: SellerLiterTariffApplyPayload,
): Promise<{ result: { pricing_mode: string }; summary: SellerPricingSummary; liter: SellerLiterTariffs }> {
  return apiFetch(`/api/warehouse/sellers/${sellerId}/pricing/`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function applySellerTariff(
  sellerId: number,
  payload: SellerTariffApplyPayload,
): Promise<{ result: { updated: number }; summary: SellerPricingSummary }> {
  return apiFetch(`/api/warehouse/sellers/${sellerId}/pricing/`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export type SellerProductTariffItem = {
  id: number
  barcode: string
  name: string
  vendor_code: string
  tech_size: string
  cell_number: string
  quantity: number
  marketplace: string
  individual_price: string | null
  price_group_id: number | null
  price_group_name: string
  effective_price: string | null
}

export type SellerProductTariffsResponse = {
  seller_id: number
  company_name: string
  pricing_mode: 'per_unit' | 'per_liter'
  items: SellerProductTariffItem[]
}

export async function fetchSellerProductTariffs(sellerId: number): Promise<SellerProductTariffsResponse> {
  return apiFetch<SellerProductTariffsResponse>(
    `/api/warehouse/sellers/${sellerId}/product-tariffs/`,
  )
}

export async function applySellerProductTariffs(
  sellerId: number,
  updates: { product_id: number; price: string }[],
): Promise<SellerProductTariffsResponse & { result: { updated: number } }> {
  return apiFetch(`/api/warehouse/sellers/${sellerId}/product-tariffs/`, {
    method: 'POST',
    body: JSON.stringify({ updates }),
  })
}

export type AdminBillingSellerRow = {
  seller_id: number
  company_name: string
  weekly_shipments: SellerWeeklyShipments | null
  liter_storage_chart?: SellerWeeklyShipments | null
  liter_shipments_chart?: SellerWeeklyShipments | null
  pricing_mode?: 'per_unit' | 'per_liter'
  error: string | null
}

export type AdminBillingResponse = {
  today?: string
  marketplace?: string
  combined?: SellerWeeklyShipments
  combined_storage?: SellerWeeklyShipments | null
  sellers?: AdminBillingSellerRow[]
  status?: 'pending'
  detail?: string
  cached_at?: string | null
  refreshing?: boolean
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

export async function fetchAdminBilling(
  marketplace: 'wb' | 'ozon' = 'wb',
  options?: { refresh?: boolean; poll?: boolean },
): Promise<AdminBillingResponse> {
  const params = new URLSearchParams()
  if (marketplace === 'ozon') params.set('marketplace', 'ozon')
  if (options?.refresh) params.set('refresh', '1')
  const query = params.toString()
  const path = `/api/sellers/admin/billing/${query ? `?${query}` : ''}`

  if (!options?.poll) {
    return apiFetch<AdminBillingResponse>(path)
  }

  for (let attempt = 0; attempt < 40; attempt += 1) {
    const pollParams = new URLSearchParams()
    if (marketplace === 'ozon') pollParams.set('marketplace', 'ozon')
    if (options?.refresh && attempt === 0) pollParams.set('refresh', '1')
    const pollQuery = pollParams.toString()
    const pollPath = `/api/sellers/admin/billing/${pollQuery ? `?${pollQuery}` : ''}`
    const result = await apiFetch<AdminBillingResponse>(pollPath)
    if (result.status !== 'pending' && result.combined) {
      return result
    }
    if (attempt === 39) {
      return result
    }
    await sleep(3000)
  }

  return { status: 'pending', detail: 'Статистика всё ещё загружается' }
}
