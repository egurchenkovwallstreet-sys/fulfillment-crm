import JsBarcode from 'jsbarcode'

export type CellLabelData = {
  product_id?: number
  seller_name: string
  cell_number: string
  barcode: string
  marketplace?: 'wb' | 'ozon' | string
  marketplace_label?: string
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
      width: 1.4,
      height: 28,
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
  const mpLabel = escapeHtml(
    data.marketplace_label || (data.marketplace === 'ozon' ? 'OZON' : 'ВБ'),
  )

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
    .zone-number {
      flex: 0 0 60%;
      display: flex;
      align-items: center;
      justify-content: center;
      overflow: hidden;
      padding: 1mm 2mm 0;
    }
    .cell-number {
      font-weight: 900;
      line-height: 0.85;
      text-align: center;
      letter-spacing: -0.02em;
    }
    .zone-meta {
      flex: 0 0 40%;
      display: flex;
      min-height: 0;
      border-top: 0.4mm solid #000;
    }
    .zone-mp {
      flex: 1 1 55%;
      display: flex;
      align-items: center;
      justify-content: center;
      overflow: hidden;
      padding: 1mm;
    }
    .mp-name {
      font-weight: 900;
      line-height: 0.78;
      text-align: center;
      letter-spacing: -0.04em;
    }
    .zone-info {
      flex: 1 1 45%;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 1.5mm 2mm;
      gap: 1mm;
      min-width: 0;
    }
    .seller {
      font-size: 11pt;
      font-weight: 800;
      text-align: center;
      line-height: 1.05;
      word-break: break-word;
      max-height: 16mm;
      overflow: hidden;
    }
    .barcode-svg { width: 100%; }
    .barcode-svg svg { width: 100%; max-width: 32mm; height: 8mm; }
    .barcode-text {
      font-size: 3.2mm;
      font-weight: 700;
      letter-spacing: 0.02em;
      line-height: 1;
      text-align: center;
      word-break: break-all;
    }
  </style>
</head>
<body>
  <article class="label">
    <section class="zone-number">
      <div class="cell-number" id="cellNum">${cellNumber}</div>
    </section>
    <section class="zone-meta">
      <div class="zone-mp">
        <div class="mp-name" id="mpName">${mpLabel}</div>
      </div>
      <div class="zone-info">
        <div class="seller">${seller}</div>
        <div class="barcode-svg">${barcodeSvg}</div>
        <div class="barcode-text">${barcodeText}</div>
      </div>
    </section>
  </article>
  <script>
    (function () {
      function fit(el, zone, fill) {
        if (!el || !zone) return;
        var maxW = zone.clientWidth * 0.94;
        var maxH = zone.clientHeight * fill;
        var size = maxH;
        el.style.fontSize = size + 'px';
        while ((el.scrollWidth > maxW || el.scrollHeight > maxH) && size > 8) {
          size -= 2;
          el.style.fontSize = size + 'px';
        }
      }
      fit(document.getElementById('cellNum'), document.querySelector('.zone-number'), 0.92);
      fit(document.getElementById('mpName'), document.querySelector('.zone-mp'), 0.95);
      ${autoPrint ? 'window.onload = function () { window.print(); window.close(); };' : ''}
    })();
  </script>
</body>
</html>`)
  win.document.close()
  return true
}
