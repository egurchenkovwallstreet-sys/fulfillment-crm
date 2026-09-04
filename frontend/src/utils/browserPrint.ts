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
  function doPrint() {
    try { window.focus(); window.print(); } catch (e) {}
    window.setTimeout(function () { try { window.close(); } catch (e2) {} }, 600);
  }
  if (!img) { doPrint(); return; }
  if (img.complete && img.naturalWidth > 0) doPrint();
  else {
    img.addEventListener('load', doPrint);
    img.addEventListener('error', function () {
      document.body.textContent = 'Ошибка загрузки изображения для печати';
    });
  }
})();`
}

function fbsStickerHtml(base64: string, autoPrint: boolean): string {
  const payload = normalizeImageBase64(base64)
  return `<!DOCTYPE html>
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
  ${autoPrint ? `<script>${autoPrintScript()}<\/script>` : ''}
</body>
</html>`
}

export function openPrintHolder(): Window | null {
  const win = window.open('', '_blank', 'width=420,height=640')
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

function printViaIframe(html: string): boolean {
  const iframe = document.createElement('iframe')
  iframe.setAttribute('aria-hidden', 'true')
  iframe.style.position = 'fixed'
  iframe.style.right = '0'
  iframe.style.bottom = '0'
  iframe.style.width = '0'
  iframe.style.height = '0'
  iframe.style.border = '0'
  document.body.appendChild(iframe)
  const doc = iframe.contentDocument
  if (!doc) {
    iframe.remove()
    return false
  }
  doc.open()
  doc.write(html)
  doc.close()
  const cleanup = () => {
    window.setTimeout(() => iframe.remove(), 1500)
  }
  const frameWin = iframe.contentWindow
  if (!frameWin) {
    cleanup()
    return false
  }
  const doPrint = () => {
    try {
      frameWin.print()
    } catch {
      // ignore
    }
    cleanup()
  }
  const img = doc.querySelector('img')
  if (img) {
    if (img.complete && img.naturalWidth > 0) {
      doPrint()
    } else {
      img.addEventListener('load', doPrint)
      img.addEventListener('error', cleanup)
    }
  } else {
    doPrint()
  }
  return true
}

/** Стикер FBS 58×40 мм (PNG base64 от WB API). */
export function printFbsSticker(
  base64: string,
  autoPrint = true,
  preopened?: Window | null,
): boolean {
  const html = fbsStickerHtml(base64, autoPrint)
  if (preopened && !preopened.closed) {
    try {
      preopened.document.open()
      preopened.document.write(html)
      preopened.document.close()
      return true
    } catch {
      try {
        preopened.close()
      } catch {
        // ignore
      }
    }
  }
  const win = window.open('', '_blank', 'width=420,height=640')
  if (win) {
    win.document.write(html)
    win.document.close()
    return true
  }
  return printViaIframe(html)
}

/** QR/ШК поставки WB — термоэтикетка 58×40 мм. */
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
