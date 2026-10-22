import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { lookupSortBarcode } from '../api/warehouse'
import { useMarketplace } from '../context/MarketplaceContext'
import { uiHint } from '../utils/uiHint'
import './SortPage.css'

const SCAN_IDLE_MS = 120

type SortState =
  | { kind: 'idle' }
  | { kind: 'ok'; companyName: string; cellNumber: string; barcode: string }
  | { kind: 'error'; message: string; barcode: string }

export function SortPage() {
  const { marketplace } = useMarketplace()
  const barcodeRef = useRef<HTMLInputElement>(null)
  const idleTimer = useRef<number>(0)
  const scanBusy = useRef(false)

  const [barcode, setBarcode] = useState('')
  const [display, setDisplay] = useState<SortState>({ kind: 'idle' })

  const focusBarcode = useCallback(() => {
    window.setTimeout(() => barcodeRef.current?.focus(), 20)
  }, [])

  useEffect(() => {
    focusBarcode()
  }, [focusBarcode])

  const submitScan = useCallback(
    async (raw: string) => {
      if (scanBusy.current) return
      const value = raw.trim()
      if (value.length < 4) return
      scanBusy.current = true
      setBarcode('')
      try {
        const result = await lookupSortBarcode(value)
        setDisplay({
          kind: 'ok',
          companyName: result.company_name,
          cellNumber: result.cell_number,
          barcode: result.barcode,
        })
      } catch (err) {
        const message =
          err instanceof Error ? err.message : 'Товар не найден в CRM'
        setDisplay({
          kind: 'error',
          message,
          barcode: value,
        })
      } finally {
        scanBusy.current = false
        focusBarcode()
      }
    },
    [focusBarcode],
  )

  function scheduleScan(value: string) {
    window.clearTimeout(idleTimer.current)
    if (value.trim().length < 4) return
    idleTimer.current = window.setTimeout(() => {
      void submitScan(value)
    }, SCAN_IDLE_MS)
  }

  function onBarcodeKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key !== 'Enter') return
    event.preventDefault()
    window.clearTimeout(idleTimer.current)
    void submitScan(event.currentTarget.value)
  }

  function onBarcodeBlur() {
    window.setTimeout(() => {
      const active = document.activeElement
      if (active instanceof HTMLElement && active.closest('[data-allow-blur]')) return
      barcodeRef.current?.focus()
    }, 0)
  }

  if (marketplace !== 'wb') {
    return (
      <div className="sort-page">
        <h1 className="sort-page__title">Сортировка</h1>
        <p className="sort-page__hint">Режим доступен только на вкладке Wildberries.</p>
      </div>
    )
  }

  return (
    <div className="sort-page">
      <h1 className="sort-page__title">Сортировка</h1>
      <p className="sort-page__hint" {...uiHint('Сканируйте баркод — крупно покажем клиента и ячейку хранения.')}>
        Сканируйте баркод товара — система покажет, кому принадлежит товар и в какой ячейке он лежит.
      </p>

      <div className="sort-display" aria-live="polite">
        {display.kind === 'ok' && (
          <>
            <div className="sort-display__block">
              <span className="sort-display__label">Клиент (ИП)</span>
              <div className="sort-display__company">{display.companyName}</div>
            </div>
            <div className="sort-display__block">
              <span className="sort-display__label">Ячейка</span>
              <div className="sort-display__cell">{display.cellNumber}</div>
              <p className="sort-display__barcode">{display.barcode}</p>
            </div>
          </>
        )}
        {display.kind === 'error' && (
          <div className="sort-display__block sort-display__block--error">
            <span className="sort-display__label">Не найдено</span>
            <div className="sort-display__company">{display.message}</div>
            <p className="sort-display__barcode">{display.barcode}</p>
          </div>
        )}
        {display.kind === 'idle' && (
          <div className="sort-display__block">
            <span className="sort-display__label">Ожидание скана</span>
            <div className="sort-display__company sort-page__hint">Отсканируйте баркод</div>
          </div>
        )}
      </div>

      <input
        ref={barcodeRef}
        className="sort-barcode-input"
        value={barcode}
        onChange={(e) => {
          setBarcode(e.target.value)
          scheduleScan(e.target.value)
        }}
        onKeyDown={onBarcodeKeyDown}
        onBlur={onBarcodeBlur}
        autoComplete="off"
        autoCorrect="off"
        spellCheck={false}
        placeholder="Сканируйте баркод"
        aria-label="Сканирование баркода для сортировки"
      />
    </div>
  )
}
