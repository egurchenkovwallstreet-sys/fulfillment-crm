import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { CrmResultModal, type CrmResultModalState } from '../components/CrmResultModal'
import '../components/PrintSuccessFlash.css'

type CrmNoticeContextValue = {
  showSuccess: (title: string, message: string) => void
  showError: (title: string, message: string) => void
  flashPrintOk: () => void
}

const CrmNoticeContext = createContext<CrmNoticeContextValue | null>(null)

const PRINT_FLASH_MS = 550

export function CrmNoticeProvider({ children }: { children: ReactNode }) {
  const [modal, setModal] = useState<CrmResultModalState | null>(null)
  const [flash, setFlash] = useState(false)

  const showSuccess = useCallback((title: string, message: string) => {
    setModal({ kind: 'success', title, message })
  }, [])

  const showError = useCallback((title: string, message: string) => {
    setModal({ kind: 'error', title, message })
  }, [])

  const flashPrintOk = useCallback(() => {
    setFlash(true)
    window.setTimeout(() => setFlash(false), PRINT_FLASH_MS)
  }, [])

  const value = useMemo(
    () => ({ showSuccess, showError, flashPrintOk }),
    [showSuccess, showError, flashPrintOk],
  )

  return (
    <CrmNoticeContext.Provider value={value}>
      {children}
      {modal && <CrmResultModal modal={modal} onClose={() => setModal(null)} />}
      {flash ? <div className="print-success-flash" aria-hidden="true" /> : null}
    </CrmNoticeContext.Provider>
  )
}

export function useCrmNotice() {
  const ctx = useContext(CrmNoticeContext)
  if (!ctx) {
    throw new Error('useCrmNotice must be used within CrmNoticeProvider')
  }
  return ctx
}
