export type FboBoxLabelData = {
  seller_name: string
  box_number: string
  date: string
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

export function printFboBoxLabel(data: FboBoxLabelData, autoPrint = true): boolean {
  const win = window.open('', '_blank', 'width=640,height=420')
  if (!win) return false

  const seller = escapeHtml(data.seller_name || '—')
  const boxNumber = escapeHtml(data.box_number || '—')
  const dateText = escapeHtml(data.date || '—')

  win.document.write(`<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8" />
  <title></title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    @page { size: 120mm 75mm; margin: 0; }
    html, body { width: 120mm; height: 75mm; }
    body {
      font-family: Arial, Helvetica, sans-serif;
      background: #fff;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }
    .label {
      width: 120mm;
      height: 75mm;
      padding: 6mm 8mm;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
    }
    .date {
      font-size: 11pt;
      color: #444;
    }
    .seller {
      font-size: 16pt;
      font-weight: 700;
      line-height: 1.2;
      text-align: center;
      flex: 1;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 2mm 0;
    }
    .box {
      font-size: 36pt;
      font-weight: 900;
      text-align: center;
      line-height: 1;
    }
    .box-caption {
      font-size: 10pt;
      text-align: center;
      color: #666;
      margin-bottom: 2mm;
    }
  </style>
</head>
<body>
  <div class="label">
    <div class="date">${dateText}</div>
    <div class="seller">${seller}</div>
    <div>
      <div class="box-caption">Короб FBO</div>
      <div class="box">${boxNumber}</div>
    </div>
  </div>
  <script>
    window.onload = function() {
      ${autoPrint ? 'setTimeout(function() { window.print(); }, 200);' : ''}
    };
  </script>
</body>
</html>`)
  win.document.close()
  return true
}
