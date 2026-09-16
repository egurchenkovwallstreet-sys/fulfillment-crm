const KIOSK_PRINT_KEY = 'crm_kiosk_print'
const PRINT_SURFACE_ATTR = 'data-crm-print-surface'

/** Запомнить режим Chrome --kiosk-printing (?print_mode=kiosk в URL ярлыка). */
const KIOSK_PRINT_PERSIST_KEY = 'crm_kiosk_print_persist'

export function initKioskPrintMode(): void {
  try {
    const params = new URLSearchParams(window.location.search)
    if (params.get('print_mode') !== 'kiosk') return
    sessionStorage.setItem(KIOSK_PRINT_KEY, '1')
    localStorage.setItem(KIOSK_PRINT_PERSIST_KEY, '1')
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
    if (sessionStorage.getItem(KIOSK_PRINT_KEY) === '1') return true
    return localStorage.getItem(KIOSK_PRINT_PERSIST_KEY) === '1'
  } catch {
    return false
  }
}

function isMainPrintSurface(): boolean {
  return document.documentElement.getAttribute(PRINT_SURFACE_ATTR) === '1'
}

/**
 * Разрешить window.print() в popup при загрузке.
 * fbs_sticker — да (стикер после скана/ЧЗ; в обычном Chrome всё равно нужен Enter).
 * document — нет (PDF, QR поставки, лента — только preview; в kiosk иначе белый экран).
 */
export function shouldBrowserAutoPrint(job: 'fbs_sticker' | 'document'): boolean {
  return job === 'fbs_sticker'
}

/**
 * Chrome с --kiosk-printing печатает без диалога. window.print() на главной вкладке CRM
 * обнуляет экран. Стикеры — только из popup с data-crm-print-surface.
 */
export function initKioskPrintGuard(): void {
  const nativePrint = window.print.bind(window)
  window.print = () => {
    if (isMainPrintSurface()) {
      nativePrint()
      return
    }
    console.warn('[CRM] Печать основного окна CRM заблокирована — стикер только через popup')
  }
}

export function markPrintSurfaceHtml(html: string): string {
  return html.replace('<html', `<html ${PRINT_SURFACE_ATTR}="1"`)
}
