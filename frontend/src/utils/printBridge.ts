const STORAGE_KEY = 'ff_print_bridge_url'
const DEFAULT_URL = 'http://127.0.0.1:9123'
const BRIDGE_TIMEOUT_MS = 2000

export type PrintJobType = 'fbs_sticker' | 'supply_sticker' | 'cell_label'

export interface PrintBridgeHealth {
  ok: boolean
  printer?: string
  win32?: boolean
  detail?: string
}

export function getPrintBridgeUrl(): string {
  try {
    return localStorage.getItem(STORAGE_KEY) || DEFAULT_URL
  } catch {
    return DEFAULT_URL
  }
}

export function setPrintBridgeUrl(url: string): void {
  localStorage.setItem(STORAGE_KEY, url.trim() || DEFAULT_URL)
}

async function bridgeFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), BRIDGE_TIMEOUT_MS)
  try {
    const response = await fetch(`${getPrintBridgeUrl()}${path}`, {
      ...init,
      signal: controller.signal,
    })
    if (!response.ok) {
      let detail = `Ошибка ${response.status}`
      try {
        const data = await response.json()
        if (data.detail) detail = String(data.detail)
      } catch {
        // ignore
      }
      throw new Error(detail)
    }
    return response.json() as Promise<T>
  } finally {
    window.clearTimeout(timer)
  }
}

export async function checkPrintBridge(): Promise<PrintBridgeHealth> {
  try {
    const data = await bridgeFetch<{ ok: boolean; printer?: string; win32?: boolean }>('/health')
    return { ok: Boolean(data.ok), printer: data.printer, win32: data.win32 }
  } catch (err) {
    return {
      ok: false,
      detail: err instanceof Error ? err.message : 'Мост печати недоступен',
    }
  }
}

export async function bridgePrintImage(jobType: PrintJobType, imageBase64: string): Promise<void> {
  await bridgeFetch('/print', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      job_type: jobType,
      image_base64: imageBase64,
    }),
  })
}
