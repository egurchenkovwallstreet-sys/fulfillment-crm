import { openPrintHolder, closePrintHolder, normalizeImageBase64 } from './browserPrint'
import { bridgePrintImage, type PrintJobType } from './printBridge'
import { getCachedPrintBridgeHealth } from './printService'

export type BatchRibbonInfoItem = {
  type: 'info'
  cell_number: string
  tech_size: string
  barcode: string
  article: string
  quantity: number
}

export type BatchRibbonStickerItem = {
  type: 'sticker'
  format: 'png' | 'pdf_bulk' | 'posting_number'
  order_id?: number
  wb_order_id?: number
  posting_id?: number
  posting_number?: string
  barcode?: string
  sticker_file?: string
  sticker_part_a?: string
  sticker_part_b?: string
  pdf_base64?: string
  requires_marking?: boolean
}

export type BatchRibbonItem = BatchRibbonInfoItem | BatchRibbonStickerItem

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function infoLabelHtml(item: BatchRibbonInfoItem): string {
  const cell = escapeHtml(item.cell_number || '—')
  const size = escapeHtml(item.tech_size || '—')
  const barcode = escapeHtml(item.barcode || '—')
  const article = escapeHtml(item.article || '—')
  const qty = escapeHtml(String(item.quantity ?? 0))
  return `
    <section class="label label--info">
      <div class="label__row"><span class="label__key">Ячейка</span><span class="label__val label__val--cell">${cell}</span></div>
      <div class="label__row"><span class="label__key">Размер</span><span class="label__val">${size}</span></div>
      <div class="label__row"><span class="label__key">Баркод</span><span class="label__val label__val--mono">${barcode}</span></div>
      <div class="label__row"><span class="label__key">Артикул</span><span class="label__val">${article}</span></div>
      <div class="label__row"><span class="label__key">Кол-во</span><span class="label__val label__val--qty">${qty} шт.</span></div>
    </section>`
}

function stickerLabelHtml(base64: string): string {
  const payload = normalizeImageBase64(base64)
  return `
    <section class="label label--sticker">
      <img src="data:image/png;base64,${payload}" alt="" />
    </section>`
}

function postingNumberLabelHtml(item: BatchRibbonStickerItem): string {
  const number = escapeHtml(item.posting_number || '—')
  const barcode = escapeHtml(item.barcode || '—')
  return `
    <section class="label label--info label--posting">
      <div class="label__title">Стикер отправления</div>
      <div class="label__row"><span class="label__key">Номер</span><span class="label__val label__val--mono">${number}</span></div>
      <div class="label__row"><span class="label__key">Баркод</span><span class="label__val label__val--mono">${barcode}</span></div>
    </section>`
}

function ribbonStyles(): string {
  return `
    * { box-sizing: border-box; margin: 0; padding: 0; }
    @page { size: 58mm 40mm; margin: 0; }
    html, body { background: #fff; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    .label {
      width: 58mm;
      height: 40mm;
      overflow: hidden;
      page-break-after: always;
      break-after: page;
      padding: 2mm 2.5mm;
      font-family: Arial, sans-serif;
    }
    .label:last-child {
      page-break-after: auto;
      break-after: auto;
    }
    .label--sticker { padding: 0; }
    .label--sticker img {
      display: block;
      width: 58mm;
      height: 40mm;
      object-fit: contain;
    }
    .label--info {
      display: flex;
      flex-direction: column;
      justify-content: center;
      gap: 0.8mm;
      border: 0.3mm solid #111;
    }
    .label__title {
      font-size: 8pt;
      font-weight: 700;
      text-align: center;
      margin-bottom: 0.5mm;
    }
    .label__row {
      display: flex;
      justify-content: space-between;
      gap: 2mm;
      font-size: 7pt;
      line-height: 1.15;
    }
    .label__key { color: #444; white-space: nowrap; }
    .label__val { font-weight: 700; text-align: right; word-break: break-all; }
    .label__val--cell { font-size: 11pt; }
    .label__val--qty { font-size: 9pt; }
    .label__val--mono { font-family: Consolas, monospace; font-size: 6.5pt; }
  `
}

function itemToHtml(item: BatchRibbonItem): string {
  if (item.type === 'info') return infoLabelHtml(item)
  if (item.format === 'png' && item.sticker_file) return stickerLabelHtml(item.sticker_file)
  return postingNumberLabelHtml(item)
}

function buildRibbonHtml(items: BatchRibbonItem[]): string {
  return `<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8" />
  <title>Лента стикеров</title>
  <style>${ribbonStyles()}</style>
</head>
<body>${items.map(itemToHtml).join('')}
</body>
</html>`
}

function drawRowsPng(title: string, rows: Array<[string, string]>): string {
  const mm = 8
  const width = 58 * mm
  const height = 40 * mm
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const ctx = canvas.getContext('2d')
  if (!ctx) return ''

  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, 0, width, height)
  ctx.strokeStyle = '#111111'
  ctx.lineWidth = 3
  ctx.strokeRect(6, 6, width - 12, height - 12)

  ctx.fillStyle = '#111111'
  ctx.textBaseline = 'middle'
  let y = 36
  if (title) {
    ctx.font = 'bold 22px Arial, sans-serif'
    ctx.textAlign = 'center'
    ctx.fillText(title, width / 2, y, width - 28)
    y += 32
  }

  ctx.textAlign = 'left'
  for (const [key, value] of rows) {
    ctx.font = '16px Arial, sans-serif'
    ctx.fillStyle = '#444444'
    ctx.fillText(key, 18, y, 120)
    ctx.font = 'bold 20px Arial, sans-serif'
    ctx.fillStyle = '#111111'
    ctx.fillText(value || '—', 140, y, width - 160)
    y += 36
  }

  const dataUrl = canvas.toDataURL('image/png')
  return normalizeImageBase64(dataUrl)
}

function infoLabelPng(item: BatchRibbonInfoItem): string {
  return drawRowsPng('', [
    ['Ячейка', item.cell_number || '—'],
    ['Размер', item.tech_size || '—'],
    ['Баркод', item.barcode || '—'],
    ['Артикул', item.article || '—'],
    ['Кол-во', `${item.quantity ?? 0} шт.`],
  ])
}

function postingLabelPng(item: BatchRibbonStickerItem): string {
  return drawRowsPng('Стикер отправления', [
    ['Номер', item.posting_number || '—'],
    ['Баркод', item.barcode || '—'],
  ])
}

function stickerPayload(item: BatchRibbonItem): string | null {
  if (item.type === 'info') return infoLabelPng(item)
  if (item.format === 'png' && item.sticker_file) {
    return normalizeImageBase64(item.sticker_file)
  }
  if (item.type === 'sticker') return postingLabelPng(item)
  return null
}

async function printRibbonViaBridge(items: BatchRibbonItem[]): Promise<void> {
  const jobType: PrintJobType = 'fbs_sticker'
  let printed = 0
  try {
    for (let index = 0; index < items.length; index += 1) {
      const payload = stickerPayload(items[index])
      if (!payload) {
        throw new Error(`Не удалось подготовить этикетку ${index + 1} из ${items.length}`)
      }
      await bridgePrintImage(jobType, payload)
      printed += 1
    }
  } catch (err) {
    if (printed > 0) {
      const reason = err instanceof Error ? err.message : 'ошибка принтера'
      throw new Error(`Напечатано ${printed} из ${items.length}. Остановка: ${reason}`)
    }
    throw err
  }
}

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms)
  })
}

async function waitForImages(doc: Document): Promise<void> {
  const images = Array.from(doc.images)
  if (!images.length) return
  await Promise.all(
    images.map((img) => {
      if (img.complete && img.naturalWidth > 0) return Promise.resolve()
      return new Promise<void>((resolve) => {
        const done = () => resolve()
        img.addEventListener('load', done, { once: true })
        img.addEventListener('error', done, { once: true })
        window.setTimeout(done, 4000)
      })
    }),
  )
}

async function printRibbonViaBrowser(
  items: BatchRibbonItem[],
  autoPrint: boolean,
  preopened?: Window | null,
): Promise<boolean> {
  const html = buildRibbonHtml(items)
  const blob = new Blob([html], { type: 'text/html;charset=utf-8' })
  const url = URL.createObjectURL(blob)

  let win = preopened && !preopened.closed ? preopened : null
  try {
    if (win) {
      win.location.replace(url)
    } else {
      win = window.open(url, '_blank', 'width=420,height=640')
    }
  } catch {
    win = null
  }

  if (!win) {
    URL.revokeObjectURL(url)
    return writeRibbonFallback(html, autoPrint)
  }

  await wait(300)
  try {
    await waitForImages(win.document)
  } catch {
    // печатаем даже если картинки грузились с ошибкой
  }

  if (autoPrint) {
    try {
      win.focus()
      win.print()
    } catch {
      URL.revokeObjectURL(url)
      return false
    }
  }
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
  return true
}

function writeRibbonFallback(html: string, autoPrint: boolean): boolean {
  const win = window.open('', '_blank', 'width=420,height=640')
  if (!win) return false
  try {
    win.document.open()
    win.document.write(html)
    win.document.close()
  } catch {
    try {
      win.close()
    } catch {
      // ignore
    }
    return false
  }
  void waitForImages(win.document).then(() => {
    if (!autoPrint) return
    try {
      win.focus()
      win.print()
    } catch {
      // ignore
    }
  })
  return true
}

export async function printBatchRibbon(
  items: BatchRibbonItem[],
  autoPrint = true,
  preopened?: Window | null,
): Promise<boolean> {
  if (!items.length) {
    closePrintHolder(preopened)
    return false
  }

  const health = getCachedPrintBridgeHealth()
  if (health?.ok) {
    closePrintHolder(preopened)
    try {
      await printRibbonViaBridge(items)
      return true
    } catch (err) {
      const message = err instanceof Error ? err.message : ''
      if (message.startsWith('Напечатано ')) {
        throw err
      }
    }
  }

  return printRibbonViaBrowser(items, autoPrint, preopened)
}

export { openPrintHolder, closePrintHolder }
