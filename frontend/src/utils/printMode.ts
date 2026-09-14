const KIOSK_PRINT_KEY = 'crm_kiosk_print'
const PRINT_SURFACE_ATTR = 'data-crm-print-surface'

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

/**
 * В Chrome с --kiosk-printing любой window.print() на вкладке CRM уходит на принтер
 * и может «обнулить» экран из-за @media print. Блокируем печать основного окна CRM.
 */
export function initKioskPrintGuard(): void {
  if (!isKioskPrintMode()) return
  const nativePrint = window.print.bind(window)
  window.print = () => {
    if (document.documentElement.getAttribute(PRINT_SURFACE_ATTR) === '1') {
      nativePrint()
      return
    }
    console.warn('[CRM] Печать основного окна заблокирована (режим kiosk-printing)')
  }
}

export function markPrintSurfaceHtml(html: string): string {
  return html.replace('<html', `<html ${PRINT_SURFACE_ATTR}="1"`)
}
