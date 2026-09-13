import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  addXlListLine,
  completeXlListSession,
  createXlListSession,
  deleteXlListLine,
  downloadXlListExcel,
  fetchXlListSession,
  fetchXlListSessions,
  scanXlListBarcode,
  updateXlListLine,
  type XlListSession,
} from '../api/xlListIntake'
import { CrmResultModal, type CrmResultModalState } from '../components/CrmResultModal'
import { hintWrapProps, uiHint } from '../utils/uiHint'

const SCAN_IDLE_MS = 120

const STATUS_LABEL: Record<XlListSession['status'], string> = {
  active: 'Сбор списка',
  completed: 'Завершён',
}

function sessionLabel(session: XlListSession): string {
  return session.title.trim() || `Список #${session.id}`
}

export function XlListIntakePanel() {
  const { sessionId } = useParams()
  const navigate = useNavigate()
  const barcodeRef = useRef<HTMLInputElement>(null)
  const idleTimer = useRef<number>(0)
  const scanBusy = useRef(false)

  const [sessions, setSessions] = useState<XlListSession[]>([])
  const [session, setSession] = useState<XlListSession | null>(null)
  const [title, setTitle] = useState('')
  const [barcode, setBarcode] = useState('')
  const [manualBarcode, setManualBarcode] = useState('')
  const [manualQty, setManualQty] = useState('1')
  const [loading, setLoading] = useState(false)
  const [resultModal, setResultModal] = useState<CrmResultModalState | null>(null)

  const activeId = sessionId ? Number(sessionId) : null
  const canEdit = session?.status !== 'completed'

  const noticeOk = (message: string, modalTitle = 'Готово') => {
    setResultModal({ kind: 'success', title: modalTitle, message })
  }
  const noticeFail = (modalTitle: string, err: unknown, fallback = 'Ошибка') => {
    const message = typeof err === 'string' ? err : err instanceof Error ? err.message : fallback
    setResultModal({ kind: 'error', title: modalTitle, message })
  }

  const focusBarcode = useCallback(() => {
    window.setTimeout(() => barcodeRef.current?.focus(), 20)
  }, [])

  const loadHome = useCallback(async () => {
    try {
      const list = await fetchXlListSessions()
      setSessions(list)
    } catch (err) {
      noticeFail('Загрузка', err, 'Ошибка загрузки')
    }
  }, [])

  useEffect(() => {
    if (!activeId) {
      setSession(null)
      void loadHome()
      return
    }
    setLoading(true)
    fetchXlListSession(activeId)
      .then(setSession)
      .catch((err) => noticeFail('Список', err, 'Список не найден'))
      .finally(() => setLoading(false))
  }, [activeId, loadHome])

  useEffect(() => {
    if (!canEdit) return
    focusBarcode()
  }, [canEdit, focusBarcode, session?.id])

  const submitScan = useCallback(
    async (raw: string) => {
      if (!activeId || !canEdit || scanBusy.current) return
      const value = raw.trim()
      if (value.length < 4) return
      scanBusy.current = true
      setBarcode('')
      try {
        const next = await scanXlListBarcode(activeId, value)
        setSession(next)
      } catch (err) {
        noticeFail('Скан', err, 'Ошибка скана')
      } finally {
        scanBusy.current = false
        focusBarcode()
      }
    },
    [activeId, canEdit, focusBarcode],
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
    if (!canEdit) return
    window.setTimeout(() => {
      const active = document.activeElement
      if (active instanceof HTMLElement && active.closest('[data-allow-blur]')) return
      barcodeRef.current?.focus()
    }, 0)
  }

  async function startNew() {
    setLoading(true)
    try {
      const created = await createXlListSession({ title: title.trim() })
      navigate(`/intake-xl/list/${created.id}`)
    } catch (err) {
      noticeFail('Список', err, 'Не удалось создать список')
    } finally {
      setLoading(false)
    }
  }

  async function handleManualAdd(event: FormEvent) {
    event.preventDefault()
    if (!activeId || !canEdit) return
    const code = manualBarcode.trim()
    const qty = parseInt(manualQty, 10)
    if (code.length < 4) {
      noticeFail('Добавление', 'Баркод слишком короткий')
      return
    }
    if (!Number.isFinite(qty) || qty < 1) {
      noticeFail('Добавление', 'Укажите количество больше нуля')
      return
    }
    setLoading(true)
    try {
      const next = await addXlListLine(activeId, code, qty)
      setSession(next)
      setManualBarcode('')
      setManualQty('1')
      noticeOk(`Добавлено: ${code} × ${qty}`)
      focusBarcode()
    } catch (err) {
      noticeFail('Добавление', err, 'Не удалось добавить')
    } finally {
      setLoading(false)
    }
  }

  async function handleUpdateLine(lineBarcode: string, quantity: number) {
    if (!activeId || !canEdit) return
    setLoading(true)
    try {
      const next = await updateXlListLine(activeId, lineBarcode, quantity)
      setSession(next)
    } catch (err) {
      noticeFail('Изменение', err, 'Не удалось изменить')
    } finally {
      setLoading(false)
    }
  }

  async function handleDeleteLine(lineBarcode: string) {
    if (!activeId || !canEdit) return
    if (!window.confirm(`Удалить баркод ${lineBarcode} из списка?`)) return
    setLoading(true)
    try {
      const next = await deleteXlListLine(activeId, lineBarcode)
      setSession(next)
    } catch (err) {
      noticeFail('Удаление', err, 'Не удалось удалить')
    } finally {
      setLoading(false)
    }
  }

  async function handleExcel() {
    if (!activeId) return
    try {
      await downloadXlListExcel(activeId)
    } catch (err) {
      noticeFail('Excel', err, 'Не удалось скачать Excel')
    }
  }

  async function handleComplete() {
    if (!activeId || !session) return
    const ok = window.confirm('Завершить список? Редактирование будет закрыто.')
    if (!ok) return
    setLoading(true)
    try {
      const next = await completeXlListSession(activeId)
      setSession(next)
      noticeOk('Список завершён.')
    } catch (err) {
      noticeFail('Список', err, 'Не удалось завершить')
    } finally {
      setLoading(false)
    }
  }

  const lastOrder = session?.last_sort_order || 0
  const lastQty = session?.last_quantity || 0

  return (
    <div className="xl-page">
      <div className="topbar">
        <div>
          <h1>Список баркодов в Excel</h1>
          <p className="xl-list-intro">
            Простой режим: собрать баркоды и количества и скачать Excel. Без ячеек, без CRM, без
            подключения WB — данные никуда не попадают, кроме файла на вашем компьютере.
          </p>
        </div>
        {session && (
          <Link
            to="/intake-xl/list"
            className="btn btn--secondary"
            data-allow-blur
            {...uiHint('Вернуться к списку сохранённых Excel-списков.')}
          >
            К списку
          </Link>
        )}
      </div>

      {!activeId && (
        <section className="xl-home">
          <div className="xl-card">
            <h2>Новый список</h2>
            <label className="xl-field">
              Название (необязательно)
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Например: Поставка 12.09"
                autoComplete="off"
              />
            </label>
            <button
              className="btn btn--primary"
              type="button"
              onClick={() => void startNew()}
              disabled={loading}
              {...uiHint('Создать новый список баркодов для Excel.')}
            >
              Начать сбор
            </button>
          </div>

          <div className="xl-card">
            <h2>Сохранённые списки</h2>
            {sessions.length === 0 && <p className="xl-muted">Пока нет списков</p>}
            {sessions.length > 0 && (
              <table className="xl-table">
                <thead>
                  <tr>
                    <th>Название</th>
                    <th>Статус</th>
                    <th>Баркодов</th>
                    <th>Штук</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {sessions.map((item) => (
                    <tr key={item.id}>
                      <td>{sessionLabel(item)}</td>
                      <td>{STATUS_LABEL[item.status]}</td>
                      <td>{item.unique_count}</td>
                      <td>{item.total_quantity}</td>
                      <td>
                        <Link
                          to={`/intake-xl/list/${item.id}`}
                          {...uiHint(
                            item.status === 'completed'
                              ? `Открыть завершённый список ${sessionLabel(item)}.`
                              : `Продолжить сбор для ${sessionLabel(item)}.`,
                          )}
                        >
                          {item.status === 'completed' ? 'Открыть' : 'Продолжить'}
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </section>
      )}

      {session && canEdit && (
        <section className="xl-scan">
          <div className="xl-session-header">
            <h2>
              {sessionLabel(session)} · {STATUS_LABEL[session.status]}
            </h2>
            <p className="xl-muted">Сканируйте по одной штуке или добавьте баркод с количеством вручную</p>
          </div>

          <div className="xl-total" aria-live="polite">
            Всего единиц: <strong>{session.total_quantity}</strong>
            <span className="xl-total__sep">·</span>
            уникальных баркодов: <strong>{session.unique_count}</strong>
          </div>

          <div className="xl-tiles">
            <div className="xl-tile xl-tile--index">
              <span className="xl-tile__label">Баркод №</span>
              <span className="xl-tile__value">{lastOrder || '—'}</span>
            </div>
            <div className="xl-tile xl-tile--qty">
              <span className="xl-tile__label">Штук этого баркода</span>
              <span className="xl-tile__value">{lastQty || '—'}</span>
            </div>
          </div>

          {session.last_barcode && <p className="xl-last-code">{session.last_barcode}</p>}

          <input
            ref={barcodeRef}
            className="xl-barcode"
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
            placeholder="Сканируйте баркод (+1 к количеству)"
          />

          <form className="xl-manual-add" onSubmit={(e) => void handleManualAdd(e)} data-allow-blur>
            <h3>Или вручную</h3>
            <div className="xl-manual-add__row">
              <label className="xl-field xl-manual-add__barcode">
                Баркод
                <input
                  value={manualBarcode}
                  onChange={(e) => setManualBarcode(e.target.value)}
                  placeholder="Введите баркод"
                  autoComplete="off"
                />
              </label>
              <label className="xl-field xl-manual-add__qty">
                Количество
                <input
                  type="number"
                  min={1}
                  value={manualQty}
                  onChange={(e) => setManualQty(e.target.value)}
                />
              </label>
              <button className="btn btn--secondary" type="submit" disabled={loading}>
                Добавить
              </button>
            </div>
          </form>

          <div className="xl-scan-actions" data-allow-blur>
            <span {...hintWrapProps('Скачать Excel с двумя колонками: баркод и количество.')}>
              <button
                className="btn btn--secondary"
                type="button"
                onClick={() => void handleExcel()}
                disabled={session.total_quantity < 1}
              >
                Скачать Excel
              </button>
            </span>
            <span {...hintWrapProps('Закрыть список для редактирования.')}>
              <button
                className="btn btn--danger"
                type="button"
                onClick={() => void handleComplete()}
                disabled={loading || session.total_quantity < 1}
              >
                Завершить список
              </button>
            </span>
          </div>

          <h2 className="xl-list-title">Список баркодов</h2>
          <table className="xl-table xl-table--scan">
            <thead>
              <tr>
                <th>№</th>
                <th>Баркод</th>
                <th>Количество</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {session.lines.map((line) => (
                <tr
                  key={line.barcode}
                  className={line.barcode === session.last_barcode ? 'xl-row--active' : undefined}
                >
                  <td>{line.sort_order}</td>
                  <td>{line.barcode}</td>
                  <td>
                    <input
                      className="xl-qty-input"
                      type="number"
                      min={0}
                      defaultValue={line.quantity}
                      onBlur={(e) => {
                        const qty = parseInt(e.target.value, 10)
                        if (Number.isFinite(qty) && qty !== line.quantity) {
                          void handleUpdateLine(line.barcode, qty)
                        }
                      }}
                    />
                  </td>
                  <td>
                    <button
                      type="button"
                      className="btn btn--danger-outline btn--small"
                      onClick={() => void handleDeleteLine(line.barcode)}
                      {...uiHint('Удалить этот баркод из списка.')}
                    >
                      Удалить
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {session && !canEdit && (
        <section className="xl-saved">
          <div className="xl-card">
            <h2>
              {sessionLabel(session)} · {STATUS_LABEL[session.status]}
            </h2>
            <p className="xl-muted">
              Баркодов: {session.unique_count}, штук: {session.total_quantity}
            </p>
            <div className="xl-saved-actions" data-allow-blur>
              <button
                className="btn btn--secondary"
                type="button"
                onClick={() => void handleExcel()}
                {...uiHint('Скачать Excel с баркодами и количествами.')}
              >
                Скачать Excel
              </button>
            </div>
          </div>

          <div className="xl-card">
            <h2>Список</h2>
            <table className="xl-table">
              <thead>
                <tr>
                  <th>№</th>
                  <th>Баркод</th>
                  <th>Количество</th>
                </tr>
              </thead>
              <tbody>
                {session.lines.map((line) => (
                  <tr key={line.barcode}>
                    <td>{line.sort_order}</td>
                    <td>{line.barcode}</td>
                    <td>{line.quantity}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {loading && activeId && !session && <p className="xl-muted">Загрузка…</p>}

      {resultModal && <CrmResultModal modal={resultModal} onClose={() => setResultModal(null)} />}
    </div>
  )
}
