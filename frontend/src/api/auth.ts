import type { LoginResponse, User } from '../types/auth'

const ACCESS_KEY = 'ff_access'
const REFRESH_KEY = 'ff_refresh'

export function getAccessToken(): string | null {
  return localStorage.getItem(ACCESS_KEY)
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_KEY)
}

export function saveTokens(access: string, refresh: string) {
  localStorage.setItem(ACCESS_KEY, access)
  localStorage.setItem(REFRESH_KEY, refresh)
}

export function clearTokens() {
  localStorage.removeItem(ACCESS_KEY)
  localStorage.removeItem(REFRESH_KEY)
}

async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  if (!headers.has('Content-Type') && options.body) {
    headers.set('Content-Type', 'application/json')
  }

  const token = getAccessToken()
  if (token) {
    headers.set('Authorization', `Bearer ${token}`)
  }

  const response = await fetch(path, { ...options, headers })

  if (response.status === 401 && getRefreshToken()) {
    const refreshed = await refreshAccessToken()
    if (refreshed) {
      headers.set('Authorization', `Bearer ${getAccessToken()}`)
      const retry = await fetch(path, { ...options, headers })
      if (!retry.ok) {
        throw new Error(await extractError(retry))
      }
      return retry.json() as Promise<T>
    }
  }

  if (!response.ok) {
    throw new Error(await extractError(response))
  }

  if (response.status === 204) {
    return undefined as T
  }

  return response.json() as Promise<T>
}

async function extractError(response: Response): Promise<string> {
  try {
    const data = await response.json()
    if (data.detail) return String(data.detail)
    const firstKey = Object.keys(data)[0]
    if (firstKey) return `${firstKey}: ${data[firstKey]}`
  } catch {
    // ignore
  }
  return `Ошибка ${response.status}`
}

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

export async function refreshAccessToken(): Promise<boolean> {
  const refresh = getRefreshToken()
  if (!refresh) return false

  try {
    const response = await fetch('/api/auth/token/refresh/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh }),
    })
    if (!response.ok) {
      clearTokens()
      return false
    }
    const data = await response.json()
    saveTokens(data.access, refresh)
    return true
  } catch {
    clearTokens()
    return false
  }
}

export function logout() {
  clearTokens()
}
