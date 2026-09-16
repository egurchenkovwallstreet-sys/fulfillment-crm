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

function isMainPrintSurface(): boolean {
  return document.documentElement.getAttribute(PRINT_SURFACE_ATTR) === '1'
}

/**
 * Chrome с --kiosk-printing печатает без диалога. Любой window.print() на вкладке CRM
 * может «обнулить» экран. Стикеры печатаются только из popup с data-crm-print-surface.
 * Защита всегда включена — Chrome kiosk не виден из JS, а sessionStorage может сброситься.
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
  window.addEventListener(
    'beforeprint',
    (event) => {
      if (!isMainPrintSurface()) {
        event.preventDefault()
        event.stopImmediatePropagation()
      }
    },
    true,
  )
}

export function markPrintSurfaceHtml(html: string): string {
  return html.replace('<html', `<html ${PRINT_SURFACE_ATTR}="1"`)
}
