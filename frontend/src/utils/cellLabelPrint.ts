import JsBarcode from 'jsbarcode'

export type CellLabelData = {
  product_id?: number
  seller_name: string
  cell_number: string
  barcode: string
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function renderBarcodeSvg(barcode: string): string {
  if (typeof document === 'undefined') return ''
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
  try {
    JsBarcode(svg, barcode, {
      format: 'CODE128',
      width: 1.6,
      height: 32,
      displayValue: false,
      margin: 0,
    })
    return svg.outerHTML
  } catch {
    return ''
  }
}

export function printCellLabel(data: CellLabelData, autoPrint = true): boolean {
  const win = window.open('', '_blank', 'width=420,height=640')
  if (!win) return false

  const seller = escapeHtml(data.seller_name || '—')
  const cellNumber = escapeHtml(data.cell_number || '—')
  const barcodeText = escapeHtml(data.barcode || '—')
  const barcodeSvg = renderBarcodeSvg(data.barcode)

  win.document.write(`<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8" />
  <title></title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    @page { size: 75mm 120mm; margin: 0; }
    html, body { width: 75mm; height: 120mm; }
    body {
      font-family: Arial, Helvetica, sans-serif;
      background: #fff;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }
    .label {
      width: 75mm;
      height: 120mm;
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }
    .zone-top {
      flex: 0 0 20%;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 0 4mm;
    }
    .seller {
      font-size: 11pt;
      font-weight: 700;
      text-align: center;
      line-height: 1.15;
      word-break: break-word;
    }
    .zone-middle {
      flex: 0 0 60%;
      display: flex;
      align-items: center;
      justify-content: center;
      overflow: hidden;
    }
    .cell-number {
      font-weight: 900;
      line-height: 0.85;
      text-align: center;
      letter-spacing: -0.02em;
    }
    .zone-bottom {
      flex: 0 0 20%;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 0 3mm;
      gap: 1mm;
    }
    .barcode-svg svg { width: 100%; max-width: 65mm; height: 10mm; }
    .barcode-text {
      font-size: 5.5mm;
      font-weight: 700;
      letter-spacing: 0.06em;
      line-height: 1;
    }
  </style>
</head>
<body>
  <article class="label">
    <header class="zone-top"><div class="seller">${seller}</div></header>
    <main class="zone-middle"><div class="cell-number" id="cellNum">${cellNumber}</div></main>
    <footer class="zone-bottom">
      <div class="barcode-svg">${barcodeSvg}</div>
      <div class="barcode-text">${barcodeText}</div>
    </footer>
  </article>
  <script>
    (function () {
      var zone = document.querySelector('.zone-middle');
      var el = document.getElementById('cellNum');
      if (!zone || !el) return;
      var maxW = zone.clientWidth * 0.92;
      var maxH = zone.clientHeight * 0.92;
      var size = maxH;
      el.style.fontSize = size + 'px';
      while ((el.scrollWidth > maxW || el.scrollHeight > maxH) && size > 8) {
        size -= 2;
        el.style.fontSize = size + 'px';
      }
      ${autoPrint ? 'window.onload = function () { window.print(); window.close(); };' : ''}
    })();
  </script>
</body>
</html>`)
  win.document.close()
  return true
}
