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
  var closed = false;
  function closeOnce() {
    if (closed) return;
    closed = true;
    window.setTimeout(function () { try { window.close(); } catch (e) {} }, 400);
  }
  window.onafterprint = closeOnce;
  function doPrint() {
    try { window.focus(); window.print(); } catch (e) {}
  }
  if (!img) { doPrint(); return; }
  if (img.complete && img.naturalWidth > 0) doPrint();
  else {
    img.addEventListener('load', doPrint);
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

/** Вызов print() на popup из opener — надёжнее inline script после async scan API. */
export function triggerPopupPrint(win: Window | null | undefined, autoPrint: boolean): void {
  if (!autoPrint || !win || win.closed) return

  try {
    win.onafterprint = () => {
      window.setTimeout(() => closePrintHolder(win), 400)
    }
  } catch {
    // ignore
  }

  const fire = () => {
    if (win.closed) return
    try {
      win.focus()
      win.print()
    } catch {
      // ignore
    }
  }

  const attempt = () => {
    if (win.closed) return
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
    win.addEventListener('load', attempt, { once: true })
  } catch {
    // ignore
  }
  window.setTimeout(attempt, 0)
  window.setTimeout(attempt, 120)
  window.setTimeout(attempt, 350)
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

function loadHtmlInPopup(win: Window, html: string, autoPrint: boolean): boolean {
  const blob = new Blob([html], { type: 'text/html;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  try {
    triggerPopupPrint(win, autoPrint)
    win.location.replace(url)
    window.setTimeout(() => URL.revokeObjectURL(url), 120_000)
    return true
  } catch {
    URL.revokeObjectURL(url)
    if (writeHtmlToPopup(win, html)) {
      triggerPopupPrint(win, autoPrint)
      return true
    }
    return false
  }
}

function openHtmlBlobWindow(html: string, autoPrint: boolean): boolean {
  const blob = new Blob([html], { type: 'text/html;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const win = window.open(url, '_blank', 'popup=1,width=420,height=640')
  if (!win) {
    URL.revokeObjectURL(url)
    return false
  }
  triggerPopupPrint(win, autoPrint)
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

/** Стикер FBS 58×40 мм (PNG base64 от WB API). autoPrint=true → kiosk без Enter. */
export function printFbsSticker(
  base64: string,
  autoPrint = true,
  preopened?: Window | null,
): boolean {
  const html = fbsStickerHtml(base64, autoPrint, !preopened || preopened.closed)
  if (preopened && !preopened.closed) {
    return loadHtmlInPopup(preopened, html, autoPrint)
  }
  return openHtmlBlobWindow(html, autoPrint)
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
