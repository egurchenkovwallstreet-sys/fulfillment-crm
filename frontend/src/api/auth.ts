import type { LoginResponse, User } from '../types/auth'
import { apiFetch } from './client'
import { clearTokens, saveTokens } from './tokens'

export { getAccessToken, getRefreshToken, clearTokens } from './tokens'

export async function login(username: string, password: string): Promise<LoginResponse> {
  const data = await apiFetch<LoginResponse>('/api/auth/login/', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  })
  saveTokens(data.access, data.refresh)
  return data
}

export async function fetchMe(): Promise<User> {
  return apiFetch<User>('/api/auth/me/')
}

export function logout() {
  clearTokens()
}
