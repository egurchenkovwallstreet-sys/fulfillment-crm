import { useCallback, useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
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
  /** Всегда открывать список по клику (даже если один код) */
  alwaysInteractive?: boolean
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
  const interactive = props.alwaysInteractive !== false

  const [open, setOpen] = useState(false)

  const close = useCallback(() => setOpen(false), [])

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, close])

  if (!interactive) {
    return <code>{display}</code>
  }

  return (
    <>
      <button
        type="button"
        className="wb-barcode-hint__trigger"
        onClick={(event) => {
          event.stopPropagation()
          setOpen(true)
        }}
        title="Показать все баркоды SKU"
      >
        <code>{display}</code>
        <span className="wb-barcode-hint__icon" aria-hidden>
          ⓘ
        </span>
      </button>
      {open
        ? createPortal(
            <div
              className="wb-barcode-hint-backdrop"
              role="presentation"
              onClick={close}
            >
              <div
                className="wb-barcode-hint-modal"
                role="dialog"
                aria-labelledby="wb-barcode-hint-title"
                onClick={(event) => event.stopPropagation()}
              >
                <h3 id="wb-barcode-hint-title">Баркоды SKU</h3>
                <div className="wb-barcode-hint-modal__section">
                  <div className="wb-barcode-hint-modal__label">Основной</div>
                  <code className="wb-barcode-hint-modal__code">{primary}</code>
                </div>
                {jitins.length > 0 ? (
                  <div className="wb-barcode-hint-modal__section">
                    <div className="wb-barcode-hint-modal__label">Джитины / доп. SKU</div>
                    <ul className="wb-barcode-hint-modal__list">
                      {jitins.map((code) => (
                        <li key={code}>
                          <code>{code}</code>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : (
                  <p className="wb-barcode-hint-modal__empty">
                    Дополнительных SKU в карточке WB для этого размера не найдено.
                  </p>
                )}
                <div className="wb-barcode-hint-modal__actions">
                  <button type="button" className="btn btn--secondary btn--small" onClick={close}>
                    Закрыть
                  </button>
                </div>
              </div>
            </div>,
            document.body,
          )
        : null}
    </>
  )
}
