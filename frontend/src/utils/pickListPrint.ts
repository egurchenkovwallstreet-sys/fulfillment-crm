import type { PickList } from '../api/orders'

const ROWS_PER_PAGE = 25

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString('ru-RU')
  } catch {
    return iso
  }
}

function rowHtml(item: PickList['items'][number]): string {
  const cell = escapeHtml(item.cell_number || '—')
  const qty = escapeHtml(String(item.quantity))
  const barcode = escapeHtml(item.barcode || '—')
  const name = escapeHtml(item.product_name || '—')
  return `
    <tr>
      <td class="col-cell"><div class="row-text row-text--cell">${cell}</div></td>
      <td class="col-qty"><div class="row-text">${qty}</div></td>
      <td class="col-barcode"><div class="row-text">${barcode}</div></td>
      <td class="col-name"><div class="row-text">${name}</div></td>
      <td class="col-check"><span class="check-box" aria-label="Отметка"></span></td>
    </tr>`
}

function tableHtml(items: PickList['items']): string {
  return `
    <table class="pick-table">
      <thead>
        <tr>
          <th class="col-cell">Ячейка</th>
          <th class="col-qty">Кол-во</th>
          <th class="col-barcode">Баркод</th>
          <th class="col-name">Название</th>
          <th class="col-check">Собрано</th>
        </tr>
      </thead>
      <tbody>${items.map(rowHtml).join('')}</tbody>
    </table>`
}

function sheetHtml(pickList: PickList, pageItems: PickList['items'], pageIndex: number, totalPages: number): string {
  const seller = escapeHtml(pickList.seller_name || '—')
  const date = escapeHtml(formatDate(pickList.created_at))
  const orders = escapeHtml(String(pickList.total_quantity))
  const listId = escapeHtml(String(pickList.id))

  const header = pageIndex === 0
    ? `
      <header class="sheet-header">
        <div class="seller-name">${seller}</div>
        <div class="sheet-meta">
          <span>Лист подбора № <strong>${listId}</strong></span>
          <span>Дата: <strong>${date}</strong></span>
          <span>Заказов: <strong>${orders}</strong></span>
        </div>
      </header>`
    : `
      <header class="sheet-header sheet-header--cont">
        <div class="sheet-meta">
          <span>Лист подбора № <strong>${listId}</strong></span>
          <span>Стр. ${pageIndex + 1} из ${totalPages}</span>
        </div>
      </header>`

  return `
    <article class="sheet">
      ${header}
      ${tableHtml(pageItems)}
    </article>`
}

const PRINT_STYLES = `
  * { box-sizing: border-box; margin: 0; padding: 0; }
  @page { size: A4 portrait; margin: 0; }
  html, body { background: #fff; margin: 0; padding: 0; }
  body {
    font-family: Arial, Helvetica, sans-serif;
    color: #0f172a;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }
  .sheet {
    width: 210mm;
    min-height: 297mm;
    height: 297mm;
    padding: 8mm 10mm 6mm;
    --pick-row-h: calc((297mm - 8mm - 6mm - 14mm - 5mm) / 25);
    overflow: hidden;
    page-break-after: always;
  }
  .sheet:last-child { page-break-after: auto; }
  .sheet-header {
    border-bottom: 1.5px solid #0f172a;
    padding-bottom: 3mm;
    margin-bottom: 2mm;
  }
  .sheet-header--cont {
    border-bottom: 1px solid #cbd5e1;
    padding-bottom: 2mm;
    margin-bottom: 2mm;
  }
  .seller-name {
    font-size: 14pt;
    font-weight: 400;
    line-height: 1.2;
    margin-bottom: 2mm;
  }
  .sheet-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 3mm 10mm;
    font-size: 10pt;
    font-weight: 400;
    color: #334155;
  }
  .sheet-meta strong {
    font-weight: 400;
    color: #0f172a;
  }
  .pick-table {
    width: 100%;
    border-collapse: collapse;
    table-layout: fixed;
    height: auto;
  }
  .pick-table thead th {
    text-align: left;
    font-size: 7pt;
    font-weight: 400;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: #64748b;
    padding: 0 1.5mm 1.5mm;
    border-bottom: 1px solid #cbd5e1;
    vertical-align: bottom;
    height: 5mm;
  }
  .pick-table tbody tr {
    border-bottom: 1px solid #e2e8f0;
    height: var(--pick-row-h);
    max-height: var(--pick-row-h);
    min-height: var(--pick-row-h);
  }
  .pick-table tbody tr:last-child { border-bottom: none; }
  .pick-table td {
    padding: 0 1.5mm;
    vertical-align: middle;
    overflow: hidden;
  }
  .col-cell { width: 11%; }
  .col-qty { width: 8%; text-align: center; }
  .col-barcode { width: 24%; }
  .col-name { width: 45%; }
  .col-check { width: 12%; text-align: center; }
  .row-text {
    font-family: Arial, Helvetica, sans-serif;
    font-size: 11pt;
    font-weight: 400;
    line-height: 1;
    word-break: break-word;
  }
  .row-text--cell {
    font-size: 14pt;
    font-weight: 700;
    line-height: 1;
  }
  .check-box {
    display: inline-block;
    width: 7mm;
    height: 7mm;
    border: 1.5px solid #0f172a;
    border-radius: 0.8mm;
    vertical-align: middle;
  }
`

export function printPickList(pickList: PickList, autoPrint = true): boolean {
  if (!pickList.items.length) return false

  const win = window.open('', '_blank', 'width=900,height=1200')
  if (!win) return false

  const pages: PickList['items'][] = []
  for (let i = 0; i < pickList.items.length; i += ROWS_PER_PAGE) {
    pages.push(pickList.items.slice(i, i + ROWS_PER_PAGE))
  }

  const sheets = pages
    .map((pageItems, index) => sheetHtml(pickList, pageItems, index, pages.length))
    .join('')

  win.document.write(`<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8" />
  <title></title>
  <style>${PRINT_STYLES}</style>
</head>
<body>
  ${sheets}
  <script>
    ${autoPrint ? 'window.onload = function () { window.print(); window.close(); };' : ''}
  </script>
</body>
</html>`)
  win.document.close()
  return true
}
