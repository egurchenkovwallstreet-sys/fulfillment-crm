import './CrmResultModal.css'

export type CrmResultModalState = {
  kind: 'success' | 'error'
  title: string
  message: string
}

type Props = {
  modal: CrmResultModalState
  onClose: () => void
}

export function CrmResultModal({ modal, onClose }: Props) {
  const isSuccess = modal.kind === 'success'

  return (
    <div
      className={`crm-result-backdrop${isSuccess ? ' crm-result-backdrop--success' : ' crm-result-backdrop--error'}`}
      role="presentation"
      onClick={onClose}
    >
      <div
        className={`crm-result${isSuccess ? ' crm-result--success' : ' crm-result--error'}`}
        role="alertdialog"
        aria-labelledby="crm-result-title"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="crm-result-title">{modal.title}</h2>
        <p className="crm-result__message">{modal.message}</p>
        <div className="crm-result__actions">
          <button type="button" className="btn btn--primary crm-result__ok" onClick={onClose}>
            Понятно
          </button>
        </div>
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
