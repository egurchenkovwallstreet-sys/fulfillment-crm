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
