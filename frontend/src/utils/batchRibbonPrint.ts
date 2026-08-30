import { openPrintHolder, closePrintHolder } from './browserPrint'

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
  const payload = (base64 || '').replace(/\s/g, '')
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

function buildRibbonHtml(items: BatchRibbonItem[], autoPrint: boolean): string {
  const body = items
    .map((item) => {
      if (item.type === 'info') return infoLabelHtml(item)
      if (item.format === 'png' && item.sticker_file) return stickerLabelHtml(item.sticker_file)
      if (item.format === 'posting_number') return postingNumberLabelHtml(item)
      return postingNumberLabelHtml(item)
    })
    .join('')

  return `<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8" />
  <title>Лента стикеров</title>
  <style>${ribbonStyles()}</style>
</head>
<body>${body}
${autoPrint ? '<script>window.onload=function(){window.print();};</script>' : ''}
</body>
</html>`
}

export function printBatchRibbon(items: BatchRibbonItem[], autoPrint = true, preopened?: Window | null): boolean {
  const html = buildRibbonHtml(items, autoPrint)
  if (preopened && !preopened.closed) {
    try {
      preopened.document.open()
      preopened.document.write(html)
      preopened.document.close()
      return true
    } catch {
      closePrintHolder(preopened)
    }
  }
  const win = window.open('', '_blank', 'width=420,height=640')
  if (!win) return false
  win.document.write(html)
  win.document.close()
  return true
}

export { openPrintHolder, closePrintHolder }
