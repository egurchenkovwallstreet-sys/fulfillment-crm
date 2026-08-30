import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { ApiError } from '../api/client'
import { batchBindScan, type BatchBindState } from '../api/assembly'
import { playAssemblyScanErrorBeep } from './AssemblyModal'
import { appendStickerHint } from './stickerLabel'
import './BatchBindPanel.css'

const EMPTY_STATE: BatchBindState = {
  barcode: '',
  sticker_scan: '',
  marking_code: '',
}

type BatchBindPanelProps = {
  sellerId: number
  disabled?: boolean
  onBound: () => void | Promise<void>
  onError?: (message: string) => void
  onSuccess?: (message: string) => void
}

export function BatchBindPanel({
  sellerId,
  disabled,
  onBound,
  onError,
  onSuccess,
}: BatchBindPanelProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [scanValue, setScanValue] = useState('')
  const [bindState, setBindState] = useState<BatchBindState>(EMPTY_STATE)
  const [requiresMarking, setRequiresMarking] = useState(false)
  const [busy, setBusy] = useState(false)
  const [modalError, setModalError] = useState<string | null>(null)

  useEffect(() => {
    if (!disabled) inputRef.current?.focus()
  }, [disabled, bindState])

  const resetBind = useCallback(() => {
    setBindState(EMPTY_STATE)
    setRequiresMarking(false)
    setScanValue('')
    inputRef.current?.focus()
  }, [])

  const processScan = useCallback(
    async (rawScan: string) => {
      const scan = rawScan.trim()
      if (!scan || busy || disabled) return
      setBusy(true)
      setModalError(null)
      try {
        const result = await batchBindScan(sellerId, {
          scan,
          ...bindState,
        })
        if (result.complete) {
          onSuccess?.(result.message || 'Связка завершена')
          resetBind()
          await onBound()
          return
        }
        setBindState({
          barcode: result.barcode || '',
          sticker_scan: result.sticker_scan || '',
          marking_code: result.marking_code || '',
        })
        setRequiresMarking(Boolean(result.requires_marking))
        setScanValue('')
      } catch (err) {
        playAssemblyScanErrorBeep()
        const message =
          err instanceof ApiError
            ? appendStickerHint(err.message, err.order as { sticker_part_a?: string; sticker_part_b?: string } | undefined)
            : err instanceof Error
              ? err.message
              : 'Ошибка связки'
        setModalError(message)
        onError?.(message)
        setScanValue('')
      } finally {
        setBusy(false)
        inputRef.current?.focus()
      }
    },
    [bindState, busy, disabled, onBound, onError, onSuccess, resetBind, sellerId],
  )

  function handleSubmit(e?: FormEvent) {
    e?.preventDefault()
    void processScan(scanValue)
  }

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') {
      e.preventDefault()
      void processScan(scanValue)
    }
  }

  const fields = requiresMarking
    ? [
        { key: 'barcode', label: '1. Баркод', value: bindState.barcode },
        { key: 'sticker_scan', label: '2. Стикер заказа', value: bindState.sticker_scan },
        { key: 'marking_code', label: '3. Честный знак', value: bindState.marking_code ? '••• привязан' : '' },
      ]
    : [
        { key: 'barcode', label: '1. Баркод', value: bindState.barcode },
        { key: 'sticker_scan', label: '2. Стикер заказа', value: bindState.sticker_scan },
      ]

  return (
    <section className="batch-bind card">
      <div className="batch-bind__head">
        <h2 className="section-title">Связка после печати</h2>
        <button type="button" className="btn btn--ghost btn--sm" onClick={resetBind} disabled={busy}>
          Сбросить
        </button>
      </div>
      <p className="batch-bind__hint">
        Сканируйте баркод, стикер заказа{requiresMarking ? ' и Честный знак' : ''} в любом порядке.
        CRM сама определит тип скана.
      </p>
      <div className="batch-bind__fields">
        {fields.map((field) => (
          <div
            key={field.key}
            className={`batch-bind__field${field.value ? ' batch-bind__field--filled' : ''}`}
          >
            <span className="batch-bind__field-label">{field.label}</span>
            <span className="batch-bind__field-value">{field.value || '—'}</span>
          </div>
        ))}
      </div>
      <form className="batch-bind__scan" onSubmit={handleSubmit}>
        <input
          ref={inputRef}
          type="text"
          className="input input--scan"
          value={scanValue}
          onChange={(e) => setScanValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Скан баркода, стикера или ЧЗ…"
          disabled={busy || disabled}
          autoComplete="off"
        />
      </form>

      {modalError && (
        <div className="batch-bind__error-modal" role="alert">
          <div className="batch-bind__error-card">
            <strong>Ошибка</strong>
            <p>{modalError}</p>
            <button type="button" className="btn btn--danger" onClick={() => setModalError(null)}>
              Понятно
            </button>
          </div>
        </div>
      )}
    </section>
  )
}
