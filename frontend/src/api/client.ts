import { clearTokens, getAccessToken, getRefreshToken, saveTokens } from './tokens'

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

async function refreshAccessToken(): Promise<boolean> {
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

export async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  if (!headers.has('Content-Type') && options.body) {
    headers.set('Content-Type', 'application/json')
  }

  const token = getAccessToken()
  if (token) {
    headers.set('Authorization', `Bearer ${token}`)
  }

  let response = await fetch(path, { ...options, headers })

  if (response.status === 401 && getRefreshToken()) {
    const refreshed = await refreshAccessToken()
    if (refreshed) {
      headers.set('Authorization', `Bearer ${getAccessToken()}`)
      response = await fetch(path, { ...options, headers })
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
