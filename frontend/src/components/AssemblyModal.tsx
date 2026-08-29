import { useEffect, useRef } from 'react'
import './AssemblyModal.css'

export type AssemblyModalState =
  | {
      kind: 'block'
      title: string
      message: string
    }
  | {
      kind: 'scan-error'
      title: string
      message: string
      onDismiss?: () => void
    }
  | {
      kind: 'confirm'
      title: string
      message: string
      confirmLabel: string
      onConfirm: () => void
    }

type Props = {
  modal: AssemblyModalState
  onClose: () => void
  loading?: boolean
}

/** Пауза после открытия — Enter со сканера не закрывает окно сразу. */
const SCAN_ERROR_ENTER_DELAY_MS = 800

export function AssemblyModal({ modal, onClose, loading = false }: Props) {
  const primaryRef = useRef<HTMLButtonElement>(null)
  const scanErrorEnterReadyRef = useRef(false)

  const isScanError = modal.kind === 'scan-error'
  const isBlock = modal.kind === 'block'

  function dismissScanError() {
    if (modal.kind !== 'scan-error') return
    modal.onDismiss?.()
    onClose()
  }

  function handlePrimaryClose() {
    if (isScanError) {
      dismissScanError()
      return
    }
    onClose()
  }

  useEffect(() => {
    scanErrorEnterReadyRef.current = false
    let enterTimer: ReturnType<typeof setTimeout> | undefined

    if (isScanError) {
      enterTimer = window.setTimeout(() => {
        scanErrorEnterReadyRef.current = true
        primaryRef.current?.focus()
      }, SCAN_ERROR_ENTER_DELAY_MS)
    } else {
      primaryRef.current?.focus()
    }

    function onKeyDown(e: KeyboardEvent) {
      if (e.key !== 'Enter') return

      if (modal.kind === 'scan-error') {
        if (!scanErrorEnterReadyRef.current) {
          e.preventDefault()
          e.stopImmediatePropagation()
          return
        }
        e.preventDefault()
        modal.onDismiss?.()
        onClose()
        return
      }

      e.preventDefault()
      if (modal.kind === 'confirm' || loading) return
      onClose()
    }

    window.addEventListener('keydown', onKeyDown, true)
    return () => {
      if (enterTimer) window.clearTimeout(enterTimer)
      window.removeEventListener('keydown', onKeyDown, true)
    }
  }, [modal, onClose, loading, isScanError])

  return (
    <div
      className={`assembly-modal-backdrop${isScanError ? ' assembly-modal-backdrop--scan-error' : ''}`}
      role="presentation"
      onClick={isScanError ? undefined : handlePrimaryClose}
    >
      <div
        className={`assembly-modal${
          isScanError
            ? ' assembly-modal--scan-error'
            : isBlock
              ? ' assembly-modal--block'
              : ''
        }`}
        role={isScanError || isBlock ? 'alertdialog' : 'dialog'}
        aria-labelledby="assembly-modal-title"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="assembly-modal-title">{modal.title}</h2>
        <p className="assembly-modal__message">{modal.message}</p>
        {isScanError && (
          <p className="assembly-modal__hint">Нажмите «Понятно» или клавишу Enter на клавиатуре</p>
        )}
        <div className="assembly-modal__actions">
          {modal.kind === 'confirm' ? (
            <>
              <button
                type="button"
                className="btn btn--primary"
                disabled={loading}
                onClick={() => {
                  modal.onConfirm()
                  onClose()
                }}
              >
                {modal.confirmLabel}
              </button>
              <button type="button" className="btn btn--secondary" onClick={onClose} disabled={loading}>
                Отмена
              </button>
            </>
          ) : (
            <button
              ref={primaryRef}
              type="button"
              className={`btn btn--primary${isScanError ? ' assembly-modal__ok' : ''}`}
              onClick={handlePrimaryClose}
            >
              Понятно
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

export function playAssemblyScanErrorBeep() {
  try {
    const ctx = new AudioContext()
    const oscillator = ctx.createOscillator()
    const gain = ctx.createGain()
    oscillator.type = 'square'
    oscillator.frequency.value = 440
    gain.gain.value = 0.08
    oscillator.connect(gain)
    gain.connect(ctx.destination)
    oscillator.start()
    window.setTimeout(() => {
      oscillator.stop()
      void ctx.close()
    }, 180)
  } catch {
    // ignore
  }
}
