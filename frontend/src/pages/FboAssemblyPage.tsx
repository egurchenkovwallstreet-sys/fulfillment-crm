import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { fetchSellers, type Seller } from '../api/warehouse'
import {
  closeFboBox,
  completeFboSession,
  createFboBox,
  createFboSession,
  downloadFboExcel,
  fetchFboSession,
  fetchFboSessions,
  pauseFboSession,
  resumeFboSession,
  scanFboBarcode,
  type FboAssemblyBox,
  type FboAssemblySession,
} from '../api/fboAssembly'
import { ApiError } from '../api/client'
import { CrmResultModal, type CrmResultModalState } from '../components/CrmResultModal'
import { useMarketplace } from '../context/MarketplaceContext'
import { printFboBoxLabel, type FboBoxLabelData } from '../utils/fboBoxLabelPrint'
import { uiHint } from '../utils/uiHint'
import './FboAssemblyPage.css'

const SCAN_IDLE_MS = 120

const STATUS_LABEL: Record<FboAssemblySession['status'], string> = {
  active: 'В работе',
  paused: 'Пауза',
  completed: 'Завершена',
}

const WRONG_SELLER_TEXT = 'Товар не этого селлера или не внесён в CRM — проверьте'

export function FboAssemblyPage() {
  const { sessionId } = useParams()
  const navigate = useNavigate()
  const { marketplace } = useMarketplace()
  const activeId = sessionId ? Number(sessionId) : null

  const barcodeRef = useRef<HTMLInputElement>(null)
  const idleTimer = useRef<number>(0)
  const scanBusy = useRef(false)

  const [sessions, setSessions] = useState<FboAssemblySession[]>([])
  const [sellers, setSellers] = useState<Seller[]>([])
  const [sellerId, setSellerId] = useState<number | ''>('')
  const [session, setSession] = useState<FboAssemblySession | null>(null)
  const [boxNumber, setBoxNumber] = useState('')
  const [barcode, setBarcode] = useState('')
  const [loading, setLoading] = useState(false)
  const [resultModal, setResultModal] = useState<CrmResultModalState | null>(null)

  const canEdit = session?.status === 'active'
  const openBoxId = session?.open_box_id ?? null
  const openBox = session?.boxes.find((b) => b.id === openBoxId) ?? null

  const focusBarcode = useCallback(() => {
    window.setTimeout(() => barcodeRef.current?.focus(), 20)
  }, [])

  const noticeFail = (title: string, err: unknown, fallback = 'Ошибка') => {
    const message = err instanceof Error ? err.message : fallback
    setResultModal({ kind: 'error', title, message })
  }

  const loadHome = useCallback(async () => {
    try {
      const [list, sellerList] = await Promise.all([fetchFboSessions(), fetchSellers()])
      setSessions(list)
      setSellers(sellerList.filter((s) => s.id))
    } catch (err) {
      noticeFail('Загрузка', err)
    }
  }, [])

  useEffect(() => {
    if (!activeId) {
      setSession(null)
      void loadHome()
      return
    }
    setLoading(true)
    fetchFboSession(activeId)
      .then(setSession)
      .catch((err) => noticeFail('Сессия', err, 'Сборка не найдена'))
      .finally(() => setLoading(false))
  }, [activeId, loadHome])

  useEffect(() => {
    if (canEdit && openBoxId) focusBarcode()
  }, [canEdit, openBoxId, focusBarcode, session?.id])

  async function startSession(e: FormEvent) {
    e.preventDefault()
    if (!sellerId) {
      noticeFail('Сборка FBO', 'Выберите клиента')
      return
    }
    setLoading(true)
    try {
      const created = await createFboSession(Number(sellerId))
      navigate(`/fbo-assembly/${created.id}`)
    } catch (err) {
      noticeFail('Сборка FBO', err, 'Не удалось начать')
    } finally {
      setLoading(false)
    }
  }

  async function handleCreateBox(e: FormEvent) {
    e.preventDefault()
    if (!activeId) return
    const num = boxNumber.trim()
    if (!num) {
      noticeFail('Короб', 'Введите номер короба')
      return
    }
    setLoading(true)
    try {
      const next = await createFboBox(activeId, num)
      setSession(next)
      setBoxNumber('')
      focusBarcode()
    } catch (err) {
      noticeFail('Короб', err)
    } finally {
      setLoading(false)
    }
  }

  const submitScan = useCallback(
    async (raw: string) => {
      if (!activeId || !openBoxId || !canEdit || scanBusy.current) return
      const value = raw.trim()
      if (value.length < 4) return
      scanBusy.current = true
      setBarcode('')
      try {
        const next = await scanFboBarcode(activeId, openBoxId, value)
        setSession(next)
      } catch (err) {
        if (err instanceof ApiError && (err.payload?.code === 'wrong_seller' || err.message.includes('не этого селлера'))) {
          setResultModal({
            kind: 'error',
            title: 'Баркод',
            message: WRONG_SELLER_TEXT,
          })
        } else {
          noticeFail('Скан', err)
        }
      } finally {
        scanBusy.current = false
        focusBarcode()
      }
    },
    [activeId, openBoxId, canEdit, focusBarcode],
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
    if (!canEdit || !openBoxId) return
    window.setTimeout(() => {
      const active = document.activeElement
      if (active instanceof HTMLElement && active.closest('[data-allow-blur]')) return
      barcodeRef.current?.focus()
    }, 0)
  }

  async function handleCloseBox() {
    if (!activeId || !openBoxId) return
    setLoading(true)
    try {
      const next = await closeFboBox(activeId, openBoxId)
      setSession(next)
      if (next.closed_box_label) {
        printFboBoxLabel(next.closed_box_label as FboBoxLabelData, true)
      }
    } catch (err) {
      noticeFail('Закрыть короб', err)
    } finally {
      setLoading(false)
    }
  }

  function handlePrintLabel(label: FboBoxLabelData) {
    if (!printFboBoxLabel(label, true)) {
      noticeFail('Печать', 'Разрешите всплывающие окна для печати')
    }
  }

  async function handleDownloadExcel() {
    if (!activeId) return
    try {
      await downloadFboExcel(activeId)
    } catch (err) {
      noticeFail('Excel', err)
    }
  }

  async function runSessionAction(action: 'pause' | 'resume' | 'complete') {
    if (!activeId) return
    setLoading(true)
    try {
      const next =
        action === 'pause'
          ? await pauseFboSession(activeId)
          : action === 'resume'
            ? await resumeFboSession(activeId)
            : await completeFboSession(activeId)
      setSession(next)
    } catch (err) {
      noticeFail('Сборка', err)
    } finally {
      setLoading(false)
    }
  }

  if (marketplace !== 'wb') {
    return (
      <div className="fbo-page">
        <h1>Сборка FBO</h1>
        <p className="fbo-muted">Доступно только на вкладке Wildberries.</p>
      </div>
    )
  }

  if (!activeId) {
    return (
      <div className="fbo-page">
        <h1>Сборка FBO</h1>
        <p className="fbo-muted" {...uiHint('Сборка поставки на склад WB: короба, скан, Excel, этикетки.')}>
          Выберите клиента и начните новую сборку или откройте сохранённую.
        </p>

        <form className="fbo-card fbo-create-box" onSubmit={(e) => void startSession(e)}>
          <label>
            Клиент (ИП)
            <select
              value={sellerId}
              onChange={(e) => setSellerId(e.target.value ? Number(e.target.value) : '')}
              required
            >
              <option value="">— выберите —</option>
              {sellers.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.company_name}
                </option>
              ))}
            </select>
          </label>
          <button className="btn btn--primary" type="submit" disabled={loading}>
            Начать сборку FBO
          </button>
        </form>

        <div className="fbo-card">
          <h2>Сборки</h2>
          {sessions.length === 0 && <p className="fbo-muted">Пока нет</p>}
          {sessions.length > 0 && (
            <table className="fbo-table">
              <thead>
                <tr>
                  <th>Клиент</th>
                  <th>Статус</th>
                  <th>Коробов</th>
                  <th>Штук</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {sessions.map((item) => (
                  <tr key={item.id}>
                    <td>{item.seller_name}</td>
                    <td>{STATUS_LABEL[item.status]}</td>
                    <td>{item.box_count}</td>
                    <td>{item.total_units}</td>
                    <td>
                      <Link to={`/fbo-assembly/${item.id}`}>Открыть</Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {resultModal && (
          <CrmResultModal modal={resultModal} onClose={() => setResultModal(null)} />
        )}
      </div>
    )
  }

  if (loading && !session) {
    return (
      <div className="fbo-page">
        <p className="fbo-muted">Загрузка…</p>
      </div>
    )
  }

  if (!session) {
    return (
      <div className="fbo-page">
        <p className="fbo-muted">Сборка не найдена</p>
        <Link to="/fbo-assembly">← К списку</Link>
      </div>
    )
  }

  const closedBoxes = session.boxes.filter((b) => b.status === 'closed')

  return (
    <div className="fbo-page">
      <p>
        <Link to="/fbo-assembly">← Все сборки FBO</Link>
      </p>
      <h1>
        {session.seller_name} · {STATUS_LABEL[session.status]}
      </h1>
      <p className="fbo-muted">
        Коробов: <strong>{session.box_count}</strong> · отсканировано штук:{' '}
        <strong>{session.total_units}</strong>
      </p>

      <div className="fbo-toolbar" data-allow-blur>
        <button type="button" className="btn btn--secondary" onClick={() => void handleDownloadExcel()}>
          Скачать Excel
        </button>
        {session.status === 'active' && (
          <button type="button" className="btn btn--secondary" onClick={() => void runSessionAction('pause')}>
            Пауза
          </button>
        )}
        {session.status === 'paused' && (
          <button type="button" className="btn btn--primary" onClick={() => void runSessionAction('resume')}>
            Продолжить
          </button>
        )}
        {session.status !== 'completed' && (
          <button type="button" className="btn btn--ghost" onClick={() => void runSessionAction('complete')}>
            Закрыть сборку
          </button>
        )}
      </div>

      {session.status === 'paused' && (
        <div className="fbo-paused-banner">Сборка на паузе — сканирование недоступно.</div>
      )}

      {canEdit && !openBoxId && (
        <form className="fbo-card fbo-create-box" onSubmit={(e) => void handleCreateBox(e)}>
          <label>
            Номер короба
            <input
              value={boxNumber}
              onChange={(e) => setBoxNumber(e.target.value)}
              placeholder="Любой текст"
              autoComplete="off"
            />
          </label>
          <button className="btn btn--primary" type="submit" disabled={loading}>
            Создать короб
          </button>
        </form>
      )}

      {canEdit && openBox && (
        <section className="fbo-card">
          <h2>Текущий короб</h2>
          <p className="fbo-open-box">{openBox.box_number}</p>
          <button
            type="button"
            className="btn btn--secondary"
            data-allow-blur
            onClick={() => handlePrintLabel(openBox.label)}
          >
            Распечатать этикетку
          </button>
          <input
            ref={barcodeRef}
            className="fbo-scan-input"
            value={barcode}
            onChange={(e) => {
              setBarcode(e.target.value)
              scheduleScan(e.target.value)
            }}
            onKeyDown={onBarcodeKeyDown}
            onBlur={onBarcodeBlur}
            autoComplete="off"
            spellCheck={false}
            placeholder="Сканируйте баркод"
          />
          {openBox.lines && openBox.lines.length > 0 && (
            <table className="fbo-table" style={{ marginTop: '1rem' }}>
              <thead>
                <tr>
                  <th>Баркод</th>
                  <th>Кол-во</th>
                </tr>
              </thead>
              <tbody>
                {openBox.lines.map((line) => (
                  <tr key={line.id}>
                    <td>{line.barcode}</td>
                    <td>{line.quantity}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div className="fbo-toolbar" style={{ marginTop: '1rem' }} data-allow-blur>
            <button type="button" className="btn btn--primary" disabled={loading} onClick={() => void handleCloseBox()}>
              Закрыть короб
            </button>
          </div>
        </section>
      )}

      <section className="fbo-card">
        <h2>Короба ({session.box_count})</h2>
        {session.boxes.length === 0 && <p className="fbo-muted">Коробов пока нет</p>}
        {session.boxes.map((box: FboAssemblyBox) => (
          <div key={box.id} className="fbo-box-row" data-allow-blur>
            <div>
              <strong>{box.box_number}</strong>
              <span className="fbo-muted">
                {' '}
                · {box.status === 'open' ? 'открыт' : 'закрыт'} · {box.total_units ?? 0} шт.
              </span>
            </div>
            <button type="button" className="btn btn--secondary btn--sm" onClick={() => handlePrintLabel(box.label)}>
              Распечатать
            </button>
          </div>
        ))}
      </section>

      {session.status === 'completed' && closedBoxes.length > 0 && (
        <p className="fbo-muted">Сборка закрыта. Этикетки коробов можно печатать повторно.</p>
      )}

      {resultModal && <CrmResultModal modal={resultModal} onClose={() => setResultModal(null)} />}
    </div>
  )
}
