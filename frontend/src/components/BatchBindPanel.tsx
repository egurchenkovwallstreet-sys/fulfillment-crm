import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { ApiError } from '../api/client'
import { batchBindScan, type BatchBindState } from '../api/assembly'
import { playAssemblyScanErrorBeep } from './AssemblyModal'
import { appendStickerHint } from '../utils/stickerLabel'
import './AssemblyModal.css'
import './BatchBindPanel.css'

const SCAN_ERROR_ENTER_DELAY_MS = 800

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
  const errorDismissRef = useRef<HTMLButtonElement>(null)
  const scanErrorEnterReadyRef = useRef(false)
  const [scanValue, setScanValue] = useState('')
  const [bindState, setBindState] = useState<BatchBindState>(EMPTY_STATE)
  const [requiresMarking, setRequiresMarking] = useState(false)
  const [busy, setBusy] = useState(false)
  const [modalError, setModalError] = useState<string | null>(null)
  const [modalErrorCode, setModalErrorCode] = useState<string | null>(null)

  const focusScanInput = useCallback(() => {
    window.setTimeout(() => {
      if (disabled) return
      inputRef.current?.focus()
      inputRef.current?.select()
    }, 0)
  }, [disabled])

  useEffect(() => {
    if (!disabled && !busy) {
      focusScanInput()
    }
  }, [disabled, busy, bindState, focusScanInput])

  useEffect(() => {
    scanErrorEnterReadyRef.current = false
    if (!modalError) return

    const enterTimer = window.setTimeout(() => {
      scanErrorEnterReadyRef.current = true
      errorDismissRef.current?.focus()
    }, SCAN_ERROR_ENTER_DELAY_MS)

    function onKeyDown(e: globalThis.KeyboardEvent) {
      if (e.key !== 'Enter' || !scanErrorEnterReadyRef.current) return
      e.preventDefault()
      e.stopImmediatePropagation()
      setModalError(null)
      setModalErrorCode(null)
      focusScanInput()
    }

    window.addEventListener('keydown', onKeyDown, true)
    return () => {
      window.clearTimeout(enterTimer)
      window.removeEventListener('keydown', onKeyDown, true)
    }
  }, [modalError, focusScanInput])

  const resetBind = useCallback(() => {
    setBindState(EMPTY_STATE)
    setRequiresMarking(false)
    setScanValue('')
    focusScanInput()
  }, [focusScanInput])

  const processScan = useCallback(
    async (rawScan: string) => {
      const scan = rawScan.trim()
      if (!scan || busy || disabled) return
      setBusy(true)
      setModalError(null)
      setModalErrorCode(null)
      let hadError = false
      try {
        const result = await batchBindScan(sellerId, {
          scan,
          ...bindState,
        })
        if (result.complete) {
          onSuccess?.(result.message || 'Связка завершена')
          resetBind()
          try {
            await onBound()
          } finally {
            focusScanInput()
          }
          return
        }
        setBindState({
          barcode: result.barcode || '',
          sticker_scan: result.sticker_scan || '',
          marking_code: result.marking_code || '',
        })
        setRequiresMarking(Boolean(result.requires_marking))
        setScanValue('')
        focusScanInput()
      } catch (err) {
        hadError = true
        playAssemblyScanErrorBeep()
        const errorCode = err instanceof ApiError ? err.code : undefined
        const message =
          err instanceof ApiError
            ? appendStickerHint(err.message, err.order as { sticker_part_a?: string; sticker_part_b?: string } | undefined)
            : err instanceof Error
              ? err.message
              : 'Ошибка связки'
        setModalErrorCode(errorCode || null)
        setModalError(message)
        onError?.(message)
        setScanValue('')
      } finally {
        setBusy(false)
        if (!hadError) {
          focusScanInput()
        }
      }
    },
    [bindState, busy, disabled, focusScanInput, onBound, onError, onSuccess, resetBind, sellerId],
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
        { key: 'sticker_scan', label: '2. QR стикера WB', value: bindState.sticker_scan },
        { key: 'marking_code', label: '3. Честный знак', value: bindState.marking_code ? '••• привязан' : '' },
      ]
    : [
        { key: 'barcode', label: '1. Баркод', value: bindState.barcode },
        { key: 'sticker_scan', label: '2. QR стикера WB', value: bindState.sticker_scan },
      ]

  const isScanError =
    modalErrorCode === 'sticker_mismatch' ||
    modalErrorCode === 'barcode_conflict' ||
    modalErrorCode === 'sticker_conflict' ||
    modalErrorCode === 'not_in_pick_list'

  function dismissError() {
    setModalError(null)
    setModalErrorCode(null)
    focusScanInput()
  }

  return (
    <section className="batch-bind batch-bind--live card">
      <div className="batch-bind__head">
        <h2 className="section-title">Связка после печати</h2>
        <button type="button" className="btn btn--ghost btn--sm" onClick={resetBind} disabled={busy}>
          Сбросить
        </button>
      </div>
      <p className="batch-bind__hint">
        Сканируйте баркод товара, затем <strong>QR-код</strong> с наклеенного стикера WB
        (буквенный код, не цифры partA/partB на этикетке){requiresMarking ? ' и Честный знак' : ''}.
        CRM проверит, что стикер относится к этому баркоду.
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
          className="batch-bind__scan-input"
          value={scanValue}
          onChange={(e) => setScanValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Скан баркода, стикера или ЧЗ…"
          disabled={busy || disabled}
          autoComplete="off"
          autoFocus
        />
      </form>

      {modalError && (
        <div
          className={`assembly-modal-backdrop${isScanError ? ' assembly-modal-backdrop--scan-error' : ''}`}
          role="alert"
        >
          <div className={`assembly-modal${isScanError ? ' assembly-modal--scan-error' : ''}`}>
            <h2>{isScanError ? 'Ошибка связки' : 'Ошибка'}</h2>
            <p className={isScanError ? 'assembly-modal__message' : undefined}>{modalError}</p>
            <div className="assembly-modal__actions">
              <button
                ref={errorDismissRef}
                type="button"
                className={`btn btn--primary${isScanError ? ' assembly-modal__ok' : ''}`}
                onClick={dismissError}
              >
                Понятно
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}
