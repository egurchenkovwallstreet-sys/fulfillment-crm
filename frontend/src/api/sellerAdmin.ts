import { apiFetch } from './client'

export type SellerManageItem = {
  id: number
  company_name: string
  is_active: boolean
  has_account: boolean
  username: string | null
  invite_token: string | null
  wb_count_new: number
  wb_count_assembly: number
  wb_count_delivery: number
  created_at: string
}

export type SellerCreatePayload = {
  company_name: string
  is_active?: boolean
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
}

export type SellerTariffApplyPayload = {
  scope: 'all' | 'group'
  price: string
  price_group_id?: number
  assign_group?: boolean
}

export async function fetchPriceGroups(): Promise<PriceGroupItem[]> {
  return apiFetch<PriceGroupItem[]>('/api/warehouse/price-groups/')
}

export async function fetchSellerPricing(sellerId: number): Promise<SellerPricingSummary> {
  return apiFetch<SellerPricingSummary>(`/api/warehouse/sellers/${sellerId}/pricing/`)
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
