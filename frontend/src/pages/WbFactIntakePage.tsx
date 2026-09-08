import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  createWbFactIntakeSession,
  deleteWbFactIntakeSession,
  fetchWbFactIntakeReport,
  fetchWbFactIntakeSession,
  fetchWbFactIntakeSessions,
  finishWbFactIntake,
  scanWbFactIntake,
  setWbFactIntakeQty,
  type WbFactIntakeLine,
  type WbFactIntakeReport,
  type WbFactIntakeSession,
} from '../api/wbFactIntake'
import { fetchProductCellLabel, fetchSellers, type Seller } from '../api/warehouse'
import { fetchSellerWarehouses, type SellerWarehouse } from '../api/sellers'
import { CrmResultModal, type CrmResultModalState } from '../components/CrmResultModal'
import { ProductPhotoThumb } from '../components/ProductPhotoThumb'
import { printCellLabel } from '../utils/cellLabelPrint'
import { useMarketplace } from '../context/MarketplaceContext'
import { uiHint } from '../utils/uiHint'
import './ArticleIntakePage.css'
import './WbFactIntakePage.css'

const STATUS_LABEL: Record<WbFactIntakeSession['status'], string> = {
  scanning: 'Приёмка',
  completed: 'Завершена',
}

function reportRows(report: WbFactIntakeReport | null | undefined): Array<{
  color: 'green' | 'yellow' | 'red'
  title: string
  rows: WbFactIntakeLine[]
}> {
  if (!report) return []
  return [
    { color: 'green', title: `Зелёные — факт совпал (${report.green_count})`, rows: report.green },
    { color: 'yellow', title: `Жёлтые — факт не совпал (${report.yellow_count})`, rows: report.yellow },
    { color: 'red', title: `Красные — в ЛК WB, на фулфилменте нет (${report.red_count})`, rows: report.red },
  ]
}

export function WbFactIntakePage() {
  const { sessionId } = useParams()
  const navigate = useNavigate()
  const { marketplace } = useMarketplace()
  const isOzon = marketplace === 'ozon'

  const barcodeRef = useRef<HTMLInputElement>(null)
  const [sessions, setSessions] = useState<WbFactIntakeSession[]>([])
  const [sellers, setSellers] = useState<Seller[]>([])
  const [warehouses, setWarehouses] = useState<SellerWarehouse[]>([])
  const [session, setSession] = useState<WbFactIntakeSession | null>(null)
  const [sellerId, setSellerId] = useState<number | ''>('')
  const [warehouseId, setWarehouseId] = useState<number | ''>('')
  const [barcode, setBarcode] = useState('')
  const [manualQty, setManualQty] = useState('1')
  const [entryMode, setEntryMode] = useState<'piece' | 'set'>('piece')
  const [qtyDraft, setQtyDraft] = useState<Record<string, string>>({})
  const [current, setCurrent] = useState<WbFactIntakeLine | null>(null)
  const [report, setReport] = useState<WbFactIntakeReport | null>(null)
  const [confirmFinish, setConfirmFinish] = useState(false)
  const [creating, setCreating] = useState(false)
  const [busyMessage, setBusyMessage] = useState('')
  const [resultModal, setResultModal] = useState<CrmResultModalState | null>(null)
  const [loading, setLoading] = useState(false)

  const activeId = sessionId ? Number(sessionId) : null
  const canEdit = session?.can_edit ?? false
  const accepted = session?.accepted || []

  const focusBarcode = useCallback(() => {
    window.setTimeout(() => barcodeRef.current?.focus(), 20)
  }, [])

  const applySession = useCallback((next: WbFactIntakeSession) => {
    setSession(next)
    const draft: Record<string, string> = {}
    for (const line of next.accepted || []) {
      draft[line.barcode] = String(line.fact_quantity ?? 0)
    }
    setQtyDraft(draft)
    if (next.report) setReport(next.report)
  }, [])

  const loadHome = useCallback(async () => {
    if (isOzon) return
    try {
      const [list, sellerList] = await Promise.all([fetchWbFactIntakeSessions(), fetchSellers()])
      setSessions(list)
      setSellers(sellerList)
    } catch (err) {
      setResultModal({
        kind: 'error',
        title: 'Ошибка',
        message: err instanceof Error ? err.message : 'Не удалось загрузить список',
      })
    }
  }, [isOzon])

  useEffect(() => {
    if (!activeId) {
      setSession(null)
      setCurrent(null)
      setReport(null)
      void loadHome()
      return
    }
    if (isOzon) return
    setLoading(true)
    fetchWbFactIntakeSession(activeId)
      .then(applySession)
      .catch((err) =>
        setResultModal({
          kind: 'error',
          title: 'Ошибка',
          message: err instanceof Error ? err.message : 'Сессия не найдена',
        }),
      )
      .finally(() => setLoading(false))
  }, [activeId, applySession, loadHome, isOzon])

  useEffect(() => {
    if (!sellerId) {
      setWarehouses([])
      setWarehouseId('')
      return
    }
    fetchSellerWarehouses(Number(sellerId))
      .then((list) => {
        setWarehouses(list)
        const enabled = list.filter((item) => item.is_enabled)
        const first = (enabled[0] || list[0])?.id
        setWarehouseId(first ?? '')
      })
      .catch(() => {
        setWarehouses([])
        setWarehouseId('')
      })
  }, [sellerId])

  useEffect(() => {
    if (canEdit) focusBarcode()
  }, [canEdit, focusBarcode, session?.id, entryMode])

  const currentLine = useMemo(() => {
    if (current) return current
    return accepted[0] || null
  }, [accepted, current])

  async function startNew() {
    if (!sellerId || !warehouseId) {
      setResultModal({ kind: 'error', title: 'Ошибка', message: 'Выберите клиента и склад FBS WB' })
      return
    }
    setCreating(true)
    try {
      const created = await createWbFactIntakeSession({
        seller_id: Number(sellerId),
        warehouse_id: Number(warehouseId),
      })
      navigate(`/intake-cards/${created.id}`)
    } catch (err) {
      setResultModal({
        kind: 'error',
        title: 'Ошибка',
        message: err instanceof Error ? err.message : 'Не удалось начать приёмку',
      })
    } finally {
      setCreating(false)
    }
  }

  async function handleScan(e?: FormEvent) {
    e?.preventDefault()
    if (!activeId || !canEdit) return
    const value = barcode.trim()
    if (value.length < 4) {
      setResultModal({ kind: 'error', title: 'Ошибка', message: 'Отсканируйте баркод' })
      return
    }
    const qty = Number(manualQty)
    if (entryMode === 'set' && (!Number.isFinite(qty) || qty < 0)) {
      setResultModal({ kind: 'error', title: 'Ошибка', message: 'Укажите количество' })
      return
    }
    setLoading(true)
    try {
      const result = await scanWbFactIntake(activeId, value, {
        scan_mode: entryMode,
        quantity: entryMode === 'set' ? qty : 0,
      })
      applySession(result.session)
      setCurrent(result.line)
      setBarcode('')
      if (result.created_cell && result.cell_label) {
        printCellLabel(result.cell_label, true)
      }
    } catch (err) {
      setResultModal({
        kind: 'error',
        title: 'Ошибка скана',
        message: err instanceof Error ? err.message : 'Скан не принят',
      })
    } finally {
      setLoading(false)
      focusBarcode()
    }
  }

  function onBarcodeKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'Enter') {
      event.preventDefault()
      void handleScan()
    }
  }

  async function handleSaveQty(line: WbFactIntakeLine) {
    if (!activeId || !canEdit) return
    const qty = Number(qtyDraft[line.barcode])
    if (!Number.isFinite(qty) || qty < 0) {
      setResultModal({ kind: 'error', title: 'Ошибка', message: 'Укажите количество' })
      return
    }
    setLoading(true)
    try {
      const result = await setWbFactIntakeQty(activeId, line.barcode, qty)
      applySession(result.session)
      setCurrent(result.line)
      setResultModal({ kind: 'success', title: 'Сохранено', message: `${line.barcode}: ${qty} шт. в CRM` })
    } catch (err) {
      setResultModal({
        kind: 'error',
        title: 'Ошибка',
        message: err instanceof Error ? err.message : 'Не удалось сохранить количество',
      })
    } finally {
      setLoading(false)
    }
  }

  async function handlePrintLabel(line: WbFactIntakeLine) {
    if (!line.product_id) return
    try {
      const label = await fetchProductCellLabel(line.product_id)
      printCellLabel(label, true)
    } catch (err) {
      setResultModal({
        kind: 'error',
        title: 'Печать',
        message: err instanceof Error ? err.message : 'Не удалось напечатать этикетку',
      })
    }
  }

  async function handleReport() {
    if (!activeId) return
    setLoading(true)
    setBusyMessage('Сверяем с ЛК WB…')
    try {
      const next = await fetchWbFactIntakeReport(activeId)
      applySession(next)
      setReport(next.report || null)
    } catch (err) {
      setResultModal({
        kind: 'error',
        title: 'Сверка',
        message: err instanceof Error ? err.message : 'Не удалось сверить с WB',
      })
    } finally {
      setLoading(false)
      setBusyMessage('')
    }
  }

  async function handleFinish() {
    if (!activeId) return
    setLoading(true)
    setBusyMessage('Выставляем остатки в ЛК WB…')
    setConfirmFinish(false)
    try {
      const next = await finishWbFactIntake(activeId)
      applySession(next)
      setReport(next.report || null)
      setResultModal({
        kind: 'success',
        title: 'Остатки выставлены',
        message: `В ЛК WB отправлено ${next.pushed ?? 0} баркодов. В CRM записан только факт приёмки.`,
      })
    } catch (err) {
      setResultModal({
        kind: 'error',
        title: 'Выгрузка в WB',
        message: err instanceof Error ? err.message : 'Не удалось выставить остатки',
      })
    } finally {
      setLoading(false)
      setBusyMessage('')
    }
  }

  async function handleDeleteSession(id: number) {
    if (!window.confirm('Удалить эту приёмку? Товары в CRM не удаляются.')) return
    setLoading(true)
    try {
      await deleteWbFactIntakeSession(id)
      if (activeId === id) navigate('/intake-cards')
      else void loadHome()
    } catch (err) {
      setResultModal({
        kind: 'error',
        title: 'Ошибка',
        message: err instanceof Error ? err.message : 'Не удалось удалить',
      })
    } finally {
      setLoading(false)
    }
  }

  if (isOzon) {
    return (
      <div className="page">
        <header className="page__header">
          <div>
            <h1>Приёмка карточек WB</h1>
            <p>Этот сценарий только для Wildberries. Переключите маркетплейс на WB.</p>
          </div>
        </header>
      </div>
    )
  }

  if (!activeId) {
    return (
      <div className="page">
        <header className="page__header">
          <div>
            <h1>Приёмка карточек WB</h1>
            <p>
              Сканируете то, что реально приехало. CRM записывает факт. В ЛК WB уходит факт минус «Новые» и «На сборке».
              Непринятые баркоды с ожиданием обнуляются в WB, каталог с нулями не трогаем.
            </p>
          </div>
        </header>
        <div className="art-home">
          <section className="art-card">
            <h2>Новая приёмка</h2>
            <label className="art-field">
              Клиент
              <select
                value={sellerId}
                onChange={(e) => setSellerId(e.target.value ? Number(e.target.value) : '')}
              >
                <option value="">— выберите —</option>
                {sellers.map((s) => (
                  <option key={s.id} value={s.id}>{s.company_name}</option>
                ))}
              </select>
            </label>
            <label className="art-field">
              Склад FBS WB
              <select
                value={warehouseId}
                onChange={(e) => setWarehouseId(e.target.value ? Number(e.target.value) : '')}
                disabled={!sellerId}
              >
                <option value="">— выберите склад —</option>
                {warehouses.map((wh) => (
                  <option key={wh.id} value={wh.id}>
                    {wh.name}{wh.is_enabled ? '' : ' (выкл.)'}
                  </option>
                ))}
              </select>
            </label>
            <div className="art-card__actions">
              <button
                type="button"
                className="btn btn--primary"
                disabled={creating || !sellerId || !warehouseId}
                onClick={() => void startNew()}
                {...uiHint('Загрузим все карточки WB и начнём приёмку на выбранном складе.')}
              >
                {creating ? 'Загружаем карточки WB…' : 'Начать'}
              </button>
            </div>
          </section>
          <section className="art-card">
            <h2>Недавние</h2>
            {sessions.length === 0 ? (
              <p className="art-muted">Пока нет сессий</p>
            ) : (
              <ul className="art-session-list">
                {sessions.slice(0, 12).map((item) => (
                  <li key={item.id} className="art-session-list__item">
                    <Link
                      to={`/intake-cards/${item.id}`}
                      {...uiHint(`Открыть приёмку #${item.id} — ${item.seller_name}.`)}
                    >
                      #{item.id} · {item.seller_name} · {item.warehouse_name} · {STATUS_LABEL[item.status]}
                      {' · '}{item.accepted_count}/{item.catalog_count}
                    </Link>
                    {!item.wb_pushed_at && (
                      <button
                        type="button"
                        className="btn btn--danger-outline btn--small"
                        disabled={loading}
                        onClick={() => void handleDeleteSession(item.id)}
                        {...uiHint('Удалить сессию. Товары в CRM останутся.')}
                      >
                        Удалить
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
        {creating && (
          <div className="fact-overlay" role="status">
            <div className="fact-overlay__card">
              <strong>Загружаем карточки WB…</strong>
              <p>Подтягиваем весь каталог и остатки выбранного склада. Это может занять минуту.</p>
            </div>
          </div>
        )}
        {resultModal && <CrmResultModal modal={resultModal} onClose={() => setResultModal(null)} />}
      </div>
    )
  }

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h1>Приёмка карточек #{activeId}</h1>
          <p>
            {session?.seller_name} · {session?.warehouse_name} · {session ? STATUS_LABEL[session.status] : '…'}
            {' · каталог '}{session?.catalog_count ?? '…'}
            {session?.wb_pushed_at ? ' · выгружено в WB' : ''}
          </p>
        </div>
        <div className="page__header-actions">
          <Link to="/intake-cards" className="btn btn--secondary" {...uiHint('Вернуться к списку приёмок карточек.')}>
            ← Список
          </Link>
          {canEdit && (
            <button
              type="button"
              className="btn btn--danger-outline"
              disabled={loading}
              onClick={() => void handleDeleteSession(activeId)}
            >
              Удалить
            </button>
          )}
        </div>
      </header>

      {canEdit && (
        <section className="art-card">
          <form className="art-scan-row" onSubmit={(e) => void handleScan(e)}>
            <label className="art-field">
              <span className="art-field__label">Баркод</span>
              <input
                ref={barcodeRef}
                value={barcode}
                onChange={(e) => setBarcode(e.target.value)}
                onKeyDown={onBarcodeKeyDown}
                placeholder="Сканируйте баркод"
                autoComplete="off"
                disabled={loading}
              />
            </label>
            <div className="art-field art-field--mode">
              <span className="art-field__label">Количество</span>
              <div className="art-mode-toggle">
                <button
                  type="button"
                  className={`btn btn--small${entryMode === 'piece' ? ' btn--primary' : ' btn--ghost'}`}
                  onClick={() => setEntryMode('piece')}
                  {...uiHint('Каждый скан этого баркода добавляет 1 шт.')}
                >
                  Поштучно
                </button>
                <button
                  type="button"
                  className={`btn btn--small${entryMode === 'set' ? ' btn--primary' : ' btn--ghost'}`}
                  onClick={() => setEntryMode('set')}
                  {...uiHint('Скан запишет указанное общее количество.')}
                >
                  Вручную
                </button>
                {entryMode === 'set' && (
                  <input
                    className="fact-qty-input"
                    value={manualQty}
                    onChange={(e) => setManualQty(e.target.value)}
                    inputMode="numeric"
                  />
                )}
              </div>
            </div>
            <button type="submit" className="btn btn--primary art-scan-row__submit" disabled={loading}>
              Принять
            </button>
          </form>

          {currentLine && (
            <div className="fact-current">
              <ProductPhotoThumb url={currentLine.photo_url} alt={currentLine.title} size="detail" />
              <div className="fact-current__meta">
                <p className="fact-current__title">{currentLine.title || currentLine.barcode}</p>
                <div>Баркод: <code>{currentLine.barcode}</code></div>
                <div>Артикул: {currentLine.vendor_code || '—'} · размер {currentLine.size_label}</div>
                {currentLine.color_label ? <div>Цвет: {currentLine.color_label}</div> : null}
                <div>Ячейка: <strong>{currentLine.cell_number || '—'}</strong></div>
                <div className="fact-current__qty">Факт CRM: {currentLine.fact_quantity} шт.</div>
              </div>
            </div>
          )}

          <div className="art-card__actions">
            <button
              type="button"
              className="btn btn--secondary"
              disabled={loading || accepted.length === 0}
              onClick={() => void handleReport()}
              {...uiHint('Сравнить факт с остатком WB + «Новые» + «На сборке».')}
            >
              Сверить с WB
            </button>
            <button
              type="button"
              className="btn btn--primary"
              disabled={loading || accepted.length === 0}
              onClick={() => {
                setConfirmFinish(true)
                if (!report) void handleReport()
              }}
              {...uiHint('CRM уже содержит факт. В ЛК WB уйдёт факт минус новые и сборка; красные обнулятся.')}
            >
              Выставить остатки в ЛК WB
            </button>
          </div>
          {confirmFinish && (
            <div className="fact-confirm">
              <p>
                В CRM останется факт приёмки. В ЛК WB: факт − «Новые» − «На сборке» (не меньше 0).
                Красные баркоды, которых нет на фулфилменте, станут 0 в WB. Каталог с нулевым ожиданием не трогаем.
              </p>
              <div className="art-card__actions">
                <button type="button" className="btn btn--primary" disabled={loading} onClick={() => void handleFinish()}>
                  Подтвердить выгрузку
                </button>
                <button type="button" className="btn btn--ghost" onClick={() => setConfirmFinish(false)}>
                  Отмена
                </button>
              </div>
            </div>
          )}
        </section>
      )}

      <section className="art-card">
        <h2>Принято ({accepted.length})</h2>
        {accepted.length === 0 ? (
          <p className="art-muted">Пока ничего не отсканировано</p>
        ) : (
          <div className="fact-table-wrap">
            <table className="fact-table">
              <thead>
                <tr>
                  <th>Фото</th>
                  <th>Баркод</th>
                  <th>Товар</th>
                  <th>Ячейка</th>
                  <th>Факт CRM</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {accepted.map((line) => (
                  <tr key={line.id}>
                    <td><ProductPhotoThumb url={line.photo_url} alt={line.title} /></td>
                    <td><code>{line.barcode}</code></td>
                    <td>
                      {line.title || '—'}
                      <div>{line.vendor_code} · {line.size_label}</div>
                    </td>
                    <td>{line.cell_number || '—'}</td>
                    <td>
                      {canEdit ? (
                        <input
                          className="fact-qty-input"
                          value={qtyDraft[line.barcode] ?? String(line.fact_quantity)}
                          onChange={(e) => setQtyDraft((prev) => ({ ...prev, [line.barcode]: e.target.value }))}
                        />
                      ) : (
                        line.fact_quantity
                      )}
                    </td>
                    <td>
                      <div className="art-row-actions">
                        {canEdit && (
                          <button type="button" className="btn btn--small btn--secondary" disabled={loading} onClick={() => void handleSaveQty(line)}>
                            Сохранить
                          </button>
                        )}
                        {line.product_id ? (
                          <button type="button" className="btn btn--small btn--ghost" onClick={() => void handlePrintLabel(line)}>
                            Этикетка
                          </button>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {report && (
        <section className="art-card">
          <h2>Сверка</h2>
          <p className="fact-legend">
            Ожидание WB = остаток FBS + «Новые» + «На сборке». CRM не уменьшается на заказы.
          </p>
          <div className="fact-legend">
            <span><i className="fact-swatch fact-swatch--green" /> {report.green_count} зелёных</span>
            <span><i className="fact-swatch fact-swatch--yellow" /> {report.yellow_count} жёлтых</span>
            <span><i className="fact-swatch fact-swatch--red" /> {report.red_count} красных</span>
          </div>
          <div className="fact-report">
            {reportRows(report).map((block) => (
              <div key={block.color} className="fact-report__block">
                <h3>{block.title}</h3>
                {block.rows.length === 0 ? (
                  <p className="art-muted">Нет</p>
                ) : (
                  <div className="fact-table-wrap">
                    <table className="fact-table">
                      <thead>
                        <tr>
                          <th>Баркод</th>
                          <th>Товар</th>
                          <th>Факт CRM</th>
                          <th>WB</th>
                          <th>Новые</th>
                          <th>Сборка</th>
                          <th>Ожидание</th>
                          <th>В ЛК WB</th>
                        </tr>
                      </thead>
                      <tbody>
                        {block.rows.map((row) => (
                          <tr key={row.barcode} className={`fact-row--${block.color}`}>
                            <td><code>{row.barcode}</code></td>
                            <td>{row.title || '—'} · {row.size_label}</td>
                            <td>{row.accepted ? row.fact_quantity : '—'}</td>
                            <td>{row.wb_stock ?? '—'}</td>
                            <td>{row.new_orders ?? 0}</td>
                            <td>{row.picking_orders ?? 0}</td>
                            <td>{row.expected ?? 0}</td>
                            <td>{row.wb_target ?? 0}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {resultModal && <CrmResultModal modal={resultModal} onClose={() => setResultModal(null)} />}
      {busyMessage && (
        <div className="fact-overlay" role="status">
          <div className="fact-overlay__card">
            <strong>{busyMessage}</strong>
            <p>Считаем остаток склада, заказы «Новые» и «На сборке».</p>
          </div>
        </div>
      )}
    </div>
  )
}
