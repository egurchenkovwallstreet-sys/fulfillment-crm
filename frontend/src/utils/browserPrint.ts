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

function openPrintDocument(html: string): Window | null {
  const win = window.open('', '_blank')
  if (!win) return null
  win.document.write(html)
  win.document.close()
  return win
}

function autoPrintScript(): string {
  return `window.onload = function () { window.print(); window.close(); };`
}

/** Стикер FBS 58×40 мм (PNG base64 от WB API). */
export function printFbsSticker(base64: string, autoPrint = true): boolean {
  const win = openPrintDocument(`<!DOCTYPE html>
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
  <img src="data:image/png;base64,${base64}" alt="" />
  ${autoPrint ? `<script>${autoPrintScript()}<\/script>` : ''}
</body>
</html>`)
  return win !== null
}

/** QR/ШК поставки WB — термоэтикетка 58×40 мм. */
export function printSupplySticker(base64: string, autoPrint = true): boolean {
  return printFbsSticker(base64, autoPrint)
}
