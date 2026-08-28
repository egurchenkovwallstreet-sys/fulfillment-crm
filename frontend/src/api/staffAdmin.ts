import { apiFetch } from './client'

export type StaffUser = {
  id: number
  username: string
  email: string
  first_name: string
  last_name: string
  role: 'manager'
  role_display: string
  is_active: boolean
  date_joined: string
  last_login: string | null
}

export type StaffCreatePayload = {
  username: string
  password: string
  email?: string
  first_name?: string
  last_name?: string
}

export type StaffUpdatePayload = {
  is_active?: boolean
  password?: string
  email?: string
  first_name?: string
  last_name?: string
}

export async function fetchStaffUsers(): Promise<StaffUser[]> {
  return apiFetch<StaffUser[]>('/api/auth/staff/')
}

export async function createStaffUser(payload: StaffCreatePayload): Promise<StaffUser> {
  return apiFetch<StaffUser>('/api/auth/staff/', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function updateStaffUser(userId: number, payload: StaffUpdatePayload): Promise<StaffUser> {
  return apiFetch<StaffUser>(`/api/auth/staff/${userId}/`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}
