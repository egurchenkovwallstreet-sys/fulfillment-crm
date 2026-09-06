const KIOSK_PRINT_KEY = 'crm_kiosk_print'

/** Запомнить режим Chrome --kiosk-printing (?print_mode=kiosk в URL ярлыка). */
export function initKioskPrintMode(): void {
  try {
    const params = new URLSearchParams(window.location.search)
    if (params.get('print_mode') !== 'kiosk') return
    sessionStorage.setItem(KIOSK_PRINT_KEY, '1')
    params.delete('print_mode')
    const query = params.toString()
    const next = `${window.location.pathname}${query ? `?${query}` : ''}${window.location.hash}`
    window.history.replaceState({}, '', next)
  } catch {
    // ignore
  }
}

export function isKioskPrintMode(): boolean {
  try {
    return sessionStorage.getItem(KIOSK_PRINT_KEY) === '1'
  } catch {
    return false
  }
}
