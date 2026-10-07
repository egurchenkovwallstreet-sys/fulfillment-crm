import './WbBarcodeHint.css'

export type WbBarcodeHintProps = {
  /** Баркод в строке (часто баркод заказа WB) */
  displayCode: string
  /** Основной баркод ячейки CRM */
  primaryBarcode?: string
  /** Все доп. sku того же размера */
  alternateBarcodes?: string[]
  /** Полный список sku (основной + джитины), если есть с API */
  wbSkuCodes?: string[]
}

function normalize(code: string): string {
  return code.trim()
}

function buildHintLines(props: WbBarcodeHintProps): { primary: string; jitins: string[] } {
  const display = normalize(props.displayCode)
  const primary = normalize(props.primaryBarcode || '') || display
  const fromApi = (props.wbSkuCodes ?? []).map(normalize).filter(Boolean)
  let jitins: string[]
  if (fromApi.length) {
    jitins = fromApi.filter((code) => code !== primary)
  } else {
    const alts = (props.alternateBarcodes ?? []).map(normalize).filter(Boolean)
    jitins = alts.filter((code) => code !== primary)
  }
  if (display && display !== primary && !jitins.includes(display)) {
    jitins = [display, ...jitins]
  }
  return { primary, jitins: [...new Set(jitins)] }
}

export function wbBarcodeHintTitle(props: WbBarcodeHintProps): string {
  const { primary, jitins } = buildHintLines(props)
  if (!jitins.length) {
    return primary ? `Основной: ${primary}` : ''
  }
  return [`Основной: ${primary}`, ...jitins.map((code) => `Джитин: ${code}`)].join('\n')
}

export function WbBarcodeHint(props: WbBarcodeHintProps) {
  const display = normalize(props.displayCode) || '—'
  const { primary, jitins } = buildHintLines(props)
  const title = wbBarcodeHintTitle(props)
  const hasHint = Boolean(title) && (jitins.length > 0 || display !== primary)

  if (!hasHint) {
    return <code>{display}</code>
  }

  return (
    <span className="wb-barcode-hint">
      <code className="wb-barcode-hint__display">{display}</code>
      <span className="wb-barcode-hint__popover" role="tooltip">
        <span className="wb-barcode-hint__primary">{primary}</span>
        {jitins.map((code) => (
          <span key={code} className="wb-barcode-hint__jitin">
            {code}
          </span>
        ))}
      </span>
    </span>
  )
}
