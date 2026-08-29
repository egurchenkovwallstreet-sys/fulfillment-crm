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

export function AssemblyModal({ modal, onClose, loading = false }: Props) {
  const primaryRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (modal.kind !== 'scan-error') {
      primaryRef.current?.focus()
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key !== 'Enter') return
      // Сканер шлёт Enter после баркода — не закрываем окно ошибки сразу.
      if (modal.kind === 'scan-error') return
      e.preventDefault()
      if (modal.kind === 'confirm' || loading) return
      onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [modal, onClose, loading])

  const isScanError = modal.kind === 'scan-error'
  const isBlock = modal.kind === 'block'

  function handlePrimaryClose() {
    if (modal.kind === 'scan-error') {
      modal.onDismiss?.()
    }
    onClose()
  }

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
