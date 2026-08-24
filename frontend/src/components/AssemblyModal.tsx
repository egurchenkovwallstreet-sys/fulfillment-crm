import './AssemblyModal.css'

export type AssemblyModalState =
  | {
      kind: 'block'
      title: string
      message: string
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
  return (
    <div className="assembly-modal-backdrop" role="presentation" onClick={onClose}>
      <div
        className={`assembly-modal${modal.kind === 'block' ? ' assembly-modal--block' : ''}`}
        role={modal.kind === 'block' ? 'alertdialog' : 'dialog'}
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
            <button type="button" className="btn btn--primary" onClick={onClose}>
              Понятно
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
