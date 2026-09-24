import { isKioskPrintMode, markPrintSurfaceHtml } from './printMode'

/**
 * Печать через Chrome: без колонтитулов (дата, URL, номер страницы).
 * Размеры по ТЗ: лист подбора A4, ячейка 75×120 мм, стикер FBS 58×40 мм.
 */

export const PRINT_SIZES = {
  pickList: 'A4 portrait',
  cellLabel: '75mm 120mm',
  fbsSticker: '58mm 40mm',
} as const

const PRINT_POPUP_NAME = 'crm_fbs_print'
const PRINT_POPUP_FEATURES = 'popup=1,width=1,height=1,left=-10000,top=-10000'

let cachedPrintWindow: Window | null = null

export function normalizeImageBase64(value: string): string {
  let raw = (value || '').trim()
  const comma = raw.indexOf(',')
  if (raw.slice(0, 12).toLowerCase().includes('data:') && comma >= 0) {
    raw = raw.slice(comma + 1)
  }
  return raw.replace(/\s/g, '')
}

function base64ToBytes(base64: string): Uint8Array {
  const binary = atob(base64)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i)
  }
  return bytes
}

function bytesToBlob(bytes: Uint8Array, type: string): Blob {
  return new Blob([Uint8Array.from(bytes)], { type })
}

function fbsStickerHtml(imgSrc: string): string {
  return markPrintSurfaceHtml(`<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8" />
  <title></title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    @page { size: ${PRINT_SIZES.fbsSticker}; margin: 0; }
    html, body {
      width: 58mm;
      height: 40mm;
      overflow: hidden;
      background: #fff;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }
    img {
      display: block;
      width: 58mm;
      height: 40mm;
      object-fit: contain;
    }
  </style>
</head>
<body>
  <img src="${imgSrc}" alt="" decoding="sync" fetchpriority="high" />
</body>
</html>`)
}

/** Дождаться загрузки PNG в popup — иначе печатается пустой лист. */
function waitForStickerImage(win: Window): Promise<void> {
  return new Promise((resolve) => {
    let settled = false
    const done = () => {
      if (settled) return
      settled = true
      resolve()
    }
    try {
      const img = win.document.querySelector('img') as HTMLImageElement | null
      if (!img) {
        done()
        return
      }
      if (img.complete && img.naturalWidth > 0) {
        done()
        return
      }
      img.addEventListener('load', done, { once: true })
      img.addEventListener('error', done, { once: true })
      const src = (img.src || '').trim()
      const fastSrc = src.startsWith('blob:') || src.startsWith('data:')
      window.setTimeout(done, fastSrc ? 250 : 1200)
    } catch {
      done()
    }
  })
}

/** Печать из popup — ждём картинку, печатаем, закрываем окно, возвращаем фокус в CRM. */
function schedulePopupPrint(win: Window, onDone?: () => void): Promise<void> {
  return waitForStickerImage(win).then(
    () =>
      new Promise((resolve) => {
        let finished = false
        const finish = () => {
          if (finished) return
          finished = true
          closePrintHolder(win)
          try {
            window.focus()
          } catch {
            // ignore
          }
          onDone?.()
          resolve(undefined)
        }

        try {
          win.addEventListener('afterprint', finish, { once: true })
        } catch {
          // ignore
        }

        window.setTimeout(() => {
          try {
            win.print()
          } catch {
            finish()
          }
        }, 30)

        // Kiosk: короткий fallback. Обычный Chrome: ждём afterprint (Enter в диалоге).
        window.setTimeout(finish, isKioskPrintMode() ? 3000 : 120_000)
      }),
  )
}

function writeHtmlToPopup(win: Window, html: string): boolean {
  try {
    win.document.open()
    win.document.write(html)
    win.document.close()
    return true
  } catch {
    return false
  }
}

function openHtmlBlobWindow(html: string): boolean {
  const blob = new Blob([html], { type: 'text/html;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const win = window.open(url, PRINT_POPUP_NAME, PRINT_POPUP_FEATURES)
  if (!win) {
    URL.revokeObjectURL(url)
    return false
  }
  cachedPrintWindow = win
  window.setTimeout(() => URL.revokeObjectURL(url), 120_000)
  return true
}

/** Декодируем PNG в кэш браузера до скана ЧЗ — popup печатает без ожидания загрузки. */
export function preloadFbsSticker(base64: string): void {
  const payload = normalizeImageBase64(base64)
  if (!payload) return
  try {
    const blob = bytesToBlob(base64ToBytes(payload), 'image/png')
    const url = URL.createObjectURL(blob)
    const img = new Image()
    img.decoding = 'sync'
    const release = () => URL.revokeObjectURL(url)
    img.onload = release
    img.onerror = release
    img.src = url
  } catch {
    const img = new Image()
    img.decoding = 'sync'
    img.src = `data:image/png;base64,${payload}`
  }
}

/** Держим окно печати открытым — следующий стикер без window.open и без «Печать…». */
export function warmFbsPrintWindow(): Window | null {
  if (cachedPrintWindow && !cachedPrintWindow.closed) {
    return cachedPrintWindow
  }
  const win = window.open('about:blank', PRINT_POPUP_NAME, PRINT_POPUP_FEATURES)
  if (!win) return null
  cachedPrintWindow = win
  try {
    win.document.open()
    win.document.write(
      '<!DOCTYPE html><html><head><title></title></head><body style="margin:0;background:#fff"></body></html>',
    )
    win.document.close()
  } catch {
    // ignore
  }
  return win
}

export function openPrintHolder(): Window | null {
  return warmFbsPrintWindow()
}

export function setPrintHolderMessage(win: Window | null, message: string) {
  if (!win || win.closed) return
  try {
    win.document.open()
    win.document.write(
      `<!DOCTYPE html><html><head><meta charset="UTF-8"><title></title></head><body style="font-family:Arial,sans-serif;padding:16px">${message}</body></html>`,
    )
    win.document.close()
  } catch {
    // ignore
  }
}

/** Сбросить popup после печати — стикер не должен висеть на экране. */
export function blankPrintHolder(win?: Window | null) {
  const target = win ?? cachedPrintWindow
  if (!target || target.closed) return
  try {
    target.document.open()
    target.document.write(
      '<!DOCTYPE html><html><head><title></title></head><body style="margin:0;background:#fff"></body></html>',
    )
    target.document.close()
  } catch {
    // ignore
  }
}

export function closePrintHolder(win?: Window | null) {
  const target = win ?? cachedPrintWindow
  if (!target || target.closed) return
  try {
    target.close()
  } catch {
    // ignore
  }
  if (target === cachedPrintWindow) {
    cachedPrintWindow = null
  }
}

/** Стикер FBS 58×40 мм. Blob URL вместо inline base64 — быстрее загрузка в popup. */
export async function printFbsSticker(
  base64: string,
  autoPrint = true,
  preopened?: Window | null,
  onPrintScheduled?: () => void,
): Promise<boolean> {
  const payload = normalizeImageBase64(base64)
  if (!payload) return false

  let imgUrl = ''
  try {
    const blob = bytesToBlob(base64ToBytes(payload), 'image/png')
    imgUrl = URL.createObjectURL(blob)
  } catch {
    imgUrl = `data:image/png;base64,${payload}`
  }

  const html = fbsStickerHtml(imgUrl)
  const win = (preopened && !preopened.closed) ? preopened : warmFbsPrintWindow()
  if (win) {
    const ok = writeHtmlToPopup(win, html)
    if (imgUrl.startsWith('blob:')) {
      window.setTimeout(() => URL.revokeObjectURL(imgUrl), 120_000)
    }
    if (ok && autoPrint) {
      await schedulePopupPrint(win, onPrintScheduled)
    } else {
      onPrintScheduled?.()
    }
    return ok
  }

  const ok = openHtmlBlobWindow(html)
  if (imgUrl.startsWith('blob:')) {
    window.setTimeout(() => URL.revokeObjectURL(imgUrl), 120_000)
  }
  if (ok && autoPrint && cachedPrintWindow && !cachedPrintWindow.closed) {
    await schedulePopupPrint(cachedPrintWindow, onPrintScheduled)
  } else {
    onPrintScheduled?.()
  }
  return ok
}

/** QR/ШК поставки WB — preview без автопечати в kiosk. */
export async function printSupplySticker(
  base64: string,
  autoPrint = true,
  preopened?: Window | null,
  onPrintScheduled?: () => void,
): Promise<boolean> {
  return printFbsSticker(base64, autoPrint, preopened, onPrintScheduled)
}

export function openPdfBase64(payload: string, filename: string) {
  const raw = payload.includes(',') ? payload.slice(payload.indexOf(',') + 1) : payload
  const binary = atob(raw.replace(/\s/g, ''))
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i)
  const blob = new Blob([bytes], { type: 'application/pdf' })
  const url = URL.createObjectURL(blob)
  const win = window.open(url, '_blank')
  if (!win) {
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    link.click()
  }
}
