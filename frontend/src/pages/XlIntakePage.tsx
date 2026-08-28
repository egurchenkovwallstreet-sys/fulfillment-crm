import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { fetchSellers, type Seller } from '../api/warehouse'
import {
  completeXlSession,
  connectXlWb,
  createXlSession,
  downloadXlExcel,
  fetchXlSession,
  fetchXlSessions,
  saveXlSession,
  scanXlBarcode,
  type XlIntakeSession,
} from '../api/xlIntake'
import './XlIntakePage.css'

const SCAN_IDLE_MS = 120
const STATUS_LABEL: Record<XlIntakeSession['status'], string> = {
  scanning: 'Сканирование',
  saved: 'Сохранена',
  applied: 'Ячейки созданы',
  completed: 'Завершена',
}

export function XlIntakePage() {
  const { sessionId } = useParams()
  const navigate = useNavigate()
  const barcodeRef = useRef<HTMLInputElement>(null)
  const idleTimer = useRef<number>(0)
  const scanBusy = useRef(false)

  const [sessions, setSessions] = useState<XlIntakeSession[]>([])
  const [sellers, setSellers] = useState<Seller[]>([])
  const [session, setSession] = useState<XlIntakeSession | null>(null)
  const [companyName, setCompanyName] = useState('')
  const [existingSellerId, setExistingSellerId] = useState<number | ''>('')
  const [barcode, setBarcode] = useState('')
  const [token, setToken] = useState('')
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [loading, setLoading] = useState(false)
  const [showUnmatched, setShowUnmatched] = useState(false)

  const activeId = sessionId ? Number(sessionId) : null
  const canScan = session?.status !== 'completed'

  const focusBarcode = useCallback(() => {
    window.setTimeout(() => barcodeRef.current?.focus(), 20)
  }, [])

  const loadHome = useCallback(async () => {
    try {
      const [list, sellerList] = await Promise.all([fetchXlSessions(), fetchSellers()])
      setSessions(list)
      setSellers(sellerList)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка загрузки')
    }
  }, [])

  useEffect(() => {
    if (!activeId) {
      setSession(null)
      void loadHome()
      return
    }
    setLoading(true)
    fetchXlSession(activeId)
      .then((data) => {
        setSession(data)
        if ((data.unmatched || []).length > 0 && data.status === 'applied') {
          setShowUnmatched(true)
        }
      })
      .catch((err) => setError(err instanceof Error ? err.message : 'Сессия не найдена'))
      .finally(() => setLoading(false))
  }, [activeId, loadHome])

  useEffect(() => {
    if (!canScan) return
    focusBarcode()
  }, [canScan, focusBarcode, session?.id])

  const submitScan = useCallback(
    async (raw: string) => {
      if (!activeId || !canScan || scanBusy.current) return
      const value = raw.trim()
      if (value.length < 4) return
      scanBusy.current = true
      setError('')
      setBarcode('')
      try {
        const next = await scanXlBarcode(activeId, value)
        setSession(next)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Ошибка скана')
      } finally {
        scanBusy.current = false
        focusBarcode()
      }
    },
    [activeId, canScan, focusBarcode],
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
    if (!canScan) return
    window.setTimeout(() => {
      const active = document.activeElement
      if (active instanceof HTMLElement && active.closest('[data-allow-blur]')) return
      barcodeRef.current?.focus()
    }, 0)
  }

  async function startNew() {
    const name = companyName.trim()
    if (!name && !existingSellerId) {
      setError('Укажите название ИП или выберите клиента')
      return
    }
    setLoading(true)
    setError('')
    try {
      const created = existingSellerId
        ? await createXlSession({ seller_id: Number(existingSellerId) })
        : await createXlSession({ company_name: name })
      navigate(`/intake-xl/${created.id}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось начать приёмку')
    } finally {
      setLoading(false)
    }
  }

  async function handleSave() {
    if (!activeId) return
    setLoading(true)
    setError('')
    setSuccess('')
    try {
      const next = await saveXlSession(activeId)
      setSession(next)
      setSuccess('Контрольная точка сохранена. Можно продолжать сканирование.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось сохранить')
    } finally {
      setLoading(false)
    }
  }

  async function handleExcel() {
    if (!activeId) return
    setError('')
    try {
      await downloadXlExcel(activeId)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось скачать Excel')
    }
  }

  async function handleConnectWb() {
    if (!activeId) return
    if (!session?.has_wb_token && !token.trim()) {
      setError('Вставьте персональный токен WB')
      return
    }
    setLoading(true)
    setError('')
    setSuccess('')
    try {
      const next = await connectXlWb(activeId, token.trim())
      setSession(next)
      setToken('')
      const created = next.created_products ?? 0
      const updated = next.updated_products ?? 0
      if (created === 0 && updated === 0) {
        setSuccess('Новых позиций для применения нет — всё уже в CRM.')
      } else if ((next.matched_count ?? 0) === 0) {
        setSuccess('')
        setError('Ни один баркод не найден в ЛК WB. Ячейки не созданы.')
      } else {
        setSuccess(
          `Ячеек создано: ${created}, обновлено: ${updated}. Можно продолжать сканирование.`,
        )
      }
      if ((next.unmatched || []).length > 0) setShowUnmatched(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось подключить WB')
    } finally {
      setLoading(false)
    }
  }

  async function handleComplete() {
    if (!activeId || !session) return
    const ok = window.confirm(
      'Завершить приёмку? Сканирование и изменения будут закрыты навсегда.',
    )
    if (!ok) return
    setLoading(true)
    setError('')
    setSuccess('')
    try {
      const next = await completeXlSession(activeId)
      setSession(next)
      setSuccess('Приёмка завершена.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось завершить')
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
          <h1>Приёмка в XL</h1>
          <p>
            Новый клиент без API: скан каждой единицы → список баркодов → Excel. Ячейки и фото
            появятся после токена WB. На склад WB не отправляем.
          </p>
        </div>
        {session && (
          <Link to="/intake-xl" className="btn btn--secondary" data-allow-blur>
            К списку
          </Link>
        )}
      </div>

      {error && <div className="dashboard-sync-msg dashboard-sync-msg--error">{error}</div>}
      {success && <div className="dashboard-sync-msg">{success}</div>}

      {!activeId && (
        <section className="xl-home">
          <div className="xl-card">
            <h2>Новая приёмка</h2>
            <label className="xl-field">
              ИП / компания
              <input
                value={companyName}
                onChange={(e) => {
                  setCompanyName(e.target.value)
                  setExistingSellerId('')
                }}
                placeholder="Например: ИП Иванов"
                autoComplete="off"
              />
            </label>
            <label className="xl-field">
              Или существующий клиент
              <select
                value={existingSellerId}
                onChange={(e) => {
                  setExistingSellerId(e.target.value ? Number(e.target.value) : '')
                  setCompanyName('')
                }}
              >
                <option value="">— новый клиент —</option>
                {sellers.map((seller) => (
                  <option key={seller.id} value={seller.id}>
                    {seller.company_name}
                  </option>
                ))}
              </select>
            </label>
            <button className="btn btn--primary" type="button" onClick={() => void startNew()} disabled={loading}>
              Начать сканирование
            </button>
          </div>

          <div className="xl-card">
            <h2>Сохранённые приёмки</h2>
            {sessions.length === 0 && <p className="xl-muted">Пока нет сессий</p>}
            {sessions.length > 0 && (
              <table className="xl-table">
                <thead>
                  <tr>
                    <th>Клиент</th>
                    <th>Статус</th>
                    <th>Баркодов</th>
                    <th>Штук</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {sessions.map((item) => (
                    <tr key={item.id}>
                      <td>{item.seller_name}</td>
                      <td>{STATUS_LABEL[item.status]}</td>
                      <td>{item.unique_count}</td>
                      <td>{item.total_quantity}</td>
                      <td>
                        <Link to={`/intake-xl/${item.id}`}>
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

      {session && canScan && (
        <section className="xl-scan">
          <div className="xl-session-header">
            <h2>
              {session.seller_name} · {STATUS_LABEL[session.status]}
            </h2>
            <p className="xl-muted">Каждый скан сохраняется автоматически</p>
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
            placeholder="Сканируйте баркод"
          />

          <div className="xl-scan-actions" data-allow-blur>
            <button
              className="btn btn--secondary"
              type="button"
              onClick={() => void handleSave()}
              disabled={loading || session.total_quantity < 1}
            >
              Сохранить
            </button>
            <button
              className="btn btn--secondary"
              type="button"
              onClick={() => void handleExcel()}
              disabled={session.total_quantity < 1}
            >
              Скачать Excel
            </button>
            <button
              className="btn btn--danger"
              type="button"
              onClick={() => void handleComplete()}
              disabled={loading || session.total_quantity < 1}
            >
              Завершить приёмку
            </button>
          </div>

          <div className="xl-connect" data-allow-blur>
            <h3>{session.status === 'applied' ? 'Обновить ячейки из WB' : 'Подключить API WB'}</h3>
            <p>
              CRM подтянет карточки, фото и расставит ячейки. После создания ячеек можно продолжать
              сканирование и снова применить WB для новых баркодов.
            </p>
            {!session.has_wb_token && (
              <label className="xl-field">
                Персональный токен WB
                <input
                  type="password"
                  value={token}
                  onChange={(e) => setToken(e.target.value)}
                  autoComplete="off"
                  data-keep-focus="token"
                />
              </label>
            )}
            {session.has_wb_token && <p className="xl-muted">Токен уже есть у клиента.</p>}
            {session.warehouse_sync_warning && (
              <p className="xl-warn">Склады WB: {session.warehouse_sync_warning}</p>
            )}
            {(session.unmatched || []).length > 0 && (
              <button className="btn btn--secondary" type="button" onClick={() => setShowUnmatched(true)}>
                Баркоды не найдены в ЛК WB ({session.unmatched.length})
              </button>
            )}
            <button
              className="btn btn--primary"
              type="button"
              onClick={() => void handleConnectWb()}
              disabled={loading || session.total_quantity < 1}
            >
              {session.status === 'applied' ? 'Применить новые баркоды' : 'Создать ячейки из каталога WB'}
            </button>
          </div>

          <h2 className="xl-list-title">Список баркодов</h2>
          <table className="xl-table xl-table--scan">
            <thead>
              <tr>
                <th>№</th>
                <th>Баркод</th>
                <th>Количество</th>
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
                  <td>{line.quantity}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {session && !canScan && (
        <section className="xl-saved">
          <div className="xl-card">
            <h2>
              {session.seller_name} · {STATUS_LABEL[session.status]}
            </h2>
            <p className="xl-muted">
              Баркодов: {session.unique_count}, штук: {session.total_quantity}
            </p>
            <div className="xl-saved-actions" data-allow-blur>
              <button className="btn btn--secondary" type="button" onClick={() => void handleExcel()}>
                Скачать Excel
              </button>
            </div>
            {(session.unmatched || []).length > 0 && (
              <button className="btn btn--secondary" type="button" onClick={() => setShowUnmatched(true)}>
                Баркоды не найдены в ЛК WB ({session.unmatched.length})
              </button>
            )}
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

      {showUnmatched && session && (
        <div className="xl-modal" role="dialog" aria-modal="true">
          <div className="xl-modal__box">
            <h2>Не найдены в личном кабинете WB</h2>
            <p>Ячейки для этих баркодов не создавались.</p>
            <table className="xl-table">
              <thead>
                <tr>
                  <th>Баркод</th>
                  <th>Количество</th>
                </tr>
              </thead>
              <tbody>
                {session.unmatched.map((row) => (
                  <tr key={row.barcode}>
                    <td>{row.barcode}</td>
                    <td>{row.quantity}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <button className="btn btn--primary" type="button" onClick={() => setShowUnmatched(false)}>
              Закрыть
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
