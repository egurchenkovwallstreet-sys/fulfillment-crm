import { markPrintSurfaceHtml } from './printMode'

/**
 * Печать через Chrome: без колонтитулов (дата, URL, номер страницы).
 * Размеры по ТЗ: лист подбора A4, ячейка 75×120 мм, стикер FBS 58×40 мм.
 * @page { margin: 0 } убирает поля, в которых Chrome рисует служебные надписи.
 */

export const PRINT_SIZES = {
  pickList: 'A4 portrait',
  cellLabel: '75mm 120mm',
  fbsSticker: '58mm 40mm',
} as const

const PRINT_POPUP_NAME = 'crm_fbs_print'

export function normalizeImageBase64(value: string): string {
  let raw = (value || '').trim()
  const comma = raw.indexOf(',')
  if (raw.slice(0, 12).toLowerCase().includes('data:') && comma >= 0) {
    raw = raw.slice(comma + 1)
  }
  return raw.replace(/\s/g, '')
}

function autoPrintScript(): string {
  return `(function () {
  var img = document.querySelector('img');
  var printed = false;
  var closed = false;
  function closeOnce() {
    if (closed) return;
    closed = true;
    window.setTimeout(function () { try { window.close(); } catch (e) {} }, 400);
  }
  window.onafterprint = closeOnce;
  function doPrint() {
    if (printed) return;
    printed = true;
    try { window.focus(); window.print(); } catch (e) {}
    window.setTimeout(closeOnce, 800);
  }
  if (!img) { doPrint(); return; }
  if (img.complete && img.naturalWidth > 0) doPrint();
  else {
    img.addEventListener('load', doPrint, { once: true });
    img.addEventListener('error', function () {
      document.body.innerHTML = '<p style="font-family:Arial,sans-serif;padding:16px">Ошибка загрузки изображения для печати</p>';
    });
  }
})();`
}

function fbsStickerHtml(base64: string, autoPrint: boolean, inlineScript: boolean): string {
  const payload = normalizeImageBase64(base64)
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
  <img src="data:image/png;base64,${payload}" alt="" />
  ${autoPrint && inlineScript ? `<script>${autoPrintScript()}<\/script>` : ''}
</body>
</html>`)
}

/** Один print() из opener после загрузки стикера в preopened popup. */
function triggerPopupPrintOnce(win: Window, autoPrint: boolean): void {
  if (!autoPrint || win.closed) return

  let printed = false

  const closeLater = () => {
    window.setTimeout(() => closePrintHolder(win), 500)
  }

  const fire = () => {
    if (printed || win.closed) return
    printed = true
    try {
      win.focus()
      win.print()
    } catch {
      // ignore
    }
    try {
      win.onafterprint = () => closePrintHolder(win)
    } catch {
      // ignore
    }
    closeLater()
  }

  const attempt = () => {
    if (printed || win.closed) return
    let img: HTMLImageElement | null = null
    try {
      img = win.document.querySelector('img')
    } catch {
      return
    }
    if (!img) {
      fire()
      return
    }
    if (img.complete && img.naturalWidth > 0) fire()
    else img.addEventListener('load', fire, { once: true })
  }

  try {
    if (win.document.readyState === 'complete') attempt()
    else win.addEventListener('load', attempt, { once: true })
  } catch {
    window.setTimeout(attempt, 200)
  }
}

function loadHtmlInPopup(win: Window, html: string, autoPrint: boolean): boolean {
  const blob = new Blob([html], { type: 'text/html;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  try {
    win.addEventListener(
      'load',
      () => triggerPopupPrintOnce(win, autoPrint),
      { once: true },
    )
    win.location.replace(url)
    window.setTimeout(() => URL.revokeObjectURL(url), 120_000)
    return true
  } catch {
    URL.revokeObjectURL(url)
    return false
  }
}

function openHtmlBlobWindow(html: string): boolean {
  const blob = new Blob([html], { type: 'text/html;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const win = window.open(url, '_blank', 'popup=1,width=420,height=640')
  if (!win) {
    URL.revokeObjectURL(url)
    return false
  }
  window.setTimeout(() => URL.revokeObjectURL(url), 120_000)
  return true
}

export function openPrintHolder(): Window | null {
  const win = window.open('about:blank', PRINT_POPUP_NAME, 'popup=1,width=420,height=640')
  if (!win) return null
  setPrintHolderMessage(win, 'Печать стикера…')
  return win
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

export function closePrintHolder(win?: Window | null) {
  if (!win || win.closed) return
  try {
    win.close()
  } catch {
    // ignore
  }
}

/** Стикер FBS 58×40 мм. Preopened popup: print из opener. Fallback: blob + inline script. */
export function printFbsSticker(
  base64: string,
  autoPrint = true,
  preopened?: Window | null,
): boolean {
  if (preopened && !preopened.closed) {
    const html = fbsStickerHtml(base64, autoPrint, false)
    return loadHtmlInPopup(preopened, html, autoPrint)
  }
  const html = fbsStickerHtml(base64, autoPrint, true)
  return openHtmlBlobWindow(html)
}

/** QR/ШК поставки WB — preview без автопечати в kiosk. */
export function printSupplySticker(
  base64: string,
  autoPrint = true,
  preopened?: Window | null,
): boolean {
  return printFbsSticker(base64, autoPrint, preopened)
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
