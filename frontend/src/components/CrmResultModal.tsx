import { useEffect, useRef } from 'react'
import './CrmResultModal.css'
import { uiHint } from '../utils/uiHint'

export type CrmResultModalState = {
  kind: 'success' | 'error'
  title: string
  message: string
}

type Props = {
  modal: CrmResultModalState
  onClose: () => void
}

const SUCCESS_AUTO_CLOSE_MS = 2400

export function CrmResultModal({ modal, onClose }: Props) {
  const isSuccess = modal.kind === 'success'
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose

  useEffect(() => {
    if (!isSuccess) return
    const timer = window.setTimeout(() => onCloseRef.current(), SUCCESS_AUTO_CLOSE_MS)
    return () => window.clearTimeout(timer)
  }, [isSuccess, modal.title, modal.message])

  return (
    <div
      className={`crm-result-backdrop${isSuccess ? ' crm-result-backdrop--success' : ' crm-result-backdrop--error'}`}
      role="presentation"
    >
      <div
        className={`crm-result${isSuccess ? ' crm-result--success' : ' crm-result--error'}`}
        role="alertdialog"
        aria-labelledby={modal.title ? 'crm-result-title' : undefined}
        aria-label={modal.title ? undefined : modal.message}
        onClick={(e) => e.stopPropagation()}
      >
        {modal.title ? <h2 id="crm-result-title">{modal.title}</h2> : null}
        <p className="crm-result__message">{modal.message}</p>
        {!isSuccess && (
          <div className="crm-result__actions">
            <button
              type="button"
              className="btn btn--primary crm-result__ok"
              onClick={onClose}
              {...uiHint('Закрыть ошибку и продолжить работу.')}
            >
              Понятно
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

export function showResult(
  setter: (value: CrmResultModalState | null) => void,
  kind: CrmResultModalState['kind'],
  title: string,
  message: string,
) {
  setter({ kind, title, message })
}
