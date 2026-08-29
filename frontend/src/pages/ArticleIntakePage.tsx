import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  completeArticleIntakeSession,
  confirmArticleGroup,
  createArticleIntakeSession,
  fetchArticleIntakeSession,
  fetchArticleIntakeSessions,
  pushArticleIntakeToMarketplace,
  scanArticleIntake,
  type ArticleGroupPreview,
  type ArticleGroupPreviewItem,
  type ArticleIntakeSession,
} from '../api/articleIntake'
import { fetchSellers, type Seller } from '../api/warehouse'
import { fetchSellerOzonWarehouses, fetchSellerWarehouses, type SellerOzonWarehouse, type SellerWarehouse } from '../api/sellers'
import { useMarketplace } from '../context/MarketplaceContext'
import './ArticleIntakePage.css'

const STATUS_LABEL: Record<ArticleIntakeSession['status'], string> = {
  active: 'Приёмка',
  completed: 'Завершена',
}

export function ArticleIntakePage() {
  const { sessionId } = useParams()
  const navigate = useNavigate()
  const { marketplace } = useMarketplace()
  const isOzon = marketplace === 'ozon'
  const mpName = isOzon ? 'Ozon' : 'WB'

  const barcodeRef = useRef<HTMLInputElement>(null)
  const [sessions, setSessions] = useState<ArticleIntakeSession[]>([])
  const [sellers, setSellers] = useState<Seller[]>([])
  const [session, setSession] = useState<ArticleIntakeSession | null>(null)
  const [companyName, setCompanyName] = useState('')
  const [existingSellerId, setExistingSellerId] = useState<number | ''>('')
  const [barcode, setBarcode] = useState('')
  const [quantityInput, setQuantityInput] = useState('1')
  const [wbWarehouses, setWbWarehouses] = useState<SellerWarehouse[]>([])
  const [ozonWarehouses, setOzonWarehouses] = useState<SellerOzonWarehouse[]>([])
  const [pushWarehouseId, setPushWarehouseId] = useState<number | ''>('')
  const [pushMode, setPushMode] = useState<'replace' | 'add'>('replace')
  const [preview, setPreview] = useState<ArticleGroupPreview | null>(null)
  const [previewItems, setPreviewItems] = useState<ArticleGroupPreviewItem[]>([])
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [loading, setLoading] = useState(false)

  const activeId = sessionId ? Number(sessionId) : null
  const canScan = session?.status === 'active'

  const focusBarcode = useCallback(() => {
    window.setTimeout(() => barcodeRef.current?.focus(), 20)
  }, [])

  const loadHome = useCallback(async () => {
    try {
      const [list, sellerList] = await Promise.all([fetchArticleIntakeSessions(), fetchSellers()])
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
    fetchArticleIntakeSession(activeId)
      .then(setSession)
      .catch((err) => setError(err instanceof Error ? err.message : 'Сессия не найдена'))
      .finally(() => setLoading(false))
  }, [activeId, loadHome])

  useEffect(() => {
    if (!session?.seller_id) return
    if (isOzon) {
      fetchSellerOzonWarehouses(session.seller_id)
        .then(setOzonWarehouses)
        .catch(() => setOzonWarehouses([]))
    } else {
      fetchSellerWarehouses(session.seller_id)
        .then(setWbWarehouses)
        .catch(() => setWbWarehouses([]))
    }
  }, [session?.seller_id, isOzon])

  useEffect(() => {
    if (canScan) focusBarcode()
  }, [canScan, focusBarcode, session?.id])

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
        ? await createArticleIntakeSession({ seller_id: Number(existingSellerId) })
        : await createArticleIntakeSession({ company_name: name })
      navigate(`/intake-article/${created.id}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось начать приёмку')
    } finally {
      setLoading(false)
    }
  }

  async function handleScan(e?: FormEvent) {
    e?.preventDefault()
    if (!activeId || !canScan) return
    const value = barcode.trim()
    const quantity = parseInt(quantityInput, 10)
    if (value.length < 4) {
      setError('Отсканируйте баркод')
      return
    }
    if (!Number.isFinite(quantity) || quantity < 0) {
      setError('Укажите количество')
      return
    }
    setLoading(true)
    setError('')
    setSuccess('')
    try {
      const result = await scanArticleIntake(activeId, value, quantity)
      setSession(result.session)
      if (result.action === 'added') {
        setSuccess(
          `+${result.quantity_added} шт. · яч. ${result.product.cell_number} · остаток ${result.product.quantity}`,
        )
        setBarcode('')
        setQuantityInput('1')
        focusBarcode()
      } else {
        setPreview(result.preview)
        setPreviewItems(result.preview.items.map((item) => ({ ...item })))
        setBarcode('')
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка скана')
    } finally {
      setLoading(false)
    }
  }

  function onBarcodeKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'Enter') {
      event.preventDefault()
      void handleScan()
    }
  }

  function toggleExcludeItem(barcodeValue: string) {
    if (!preview || preview.scanned_barcode === barcodeValue) return
    const item = previewItems.find((row) => row.barcode === barcodeValue)
    if (!item) return
    if (!item.excluded) {
      const label = item.size_label || barcodeValue
      if (
        !window.confirm(
          `Удалить ячейку для размера ${label}?\n\nРазмер не будет создан в CRM.`,
        )
      ) {
        return
      }
    }
    setPreviewItems((prev) =>
      prev.map((row) =>
        row.barcode === barcodeValue ? { ...row, excluded: !row.excluded } : row,
      ),
    )
  }

  async function handleConfirmGroup() {
    if (!activeId || !preview) return
    const activeCount = previewItems.filter((item) => !item.excluded).length
    if (activeCount === 0) {
      setError('Оставьте хотя бы один размер')
      return
    }
    if (
      !window.confirm(
        `Создать ${activeCount} ячеек для артикула ${preview.vendor_code || preview.article_id}, цвет «${preview.color_label}»?`,
      )
    ) {
      return
    }
    setLoading(true)
    setError('')
    try {
      const result = await confirmArticleGroup(activeId, {
        scanned_barcode: preview.scanned_barcode,
        scanned_quantity: preview.scanned_quantity,
        items: previewItems.map((item) => ({
          barcode: item.barcode,
          cell_number: item.cell_number,
          excluded: item.excluded,
        })),
      })
      setSession(result.session)
      setPreview(null)
      setPreviewItems([])
      setSuccess(
        `Создано ${result.created_products} ячеек (${result.created_cells.join(', ')}), +${result.added_units} шт.`,
      )
      focusBarcode()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка подтверждения')
    } finally {
      setLoading(false)
    }
  }

  async function handlePush() {
    if (!activeId || !pushWarehouseId) {
      setError('Выберите склад для выгрузки')
      return
    }
    const modeLabel = pushMode === 'replace' ? 'заменить остатки' : 'прибавить к маркетплейсу'
    if (!window.confirm(`Выгрузить остатки из CRM на ${mpName} (${modeLabel})?`)) return
    setLoading(true)
    setError('')
    try {
      const result = await pushArticleIntakeToMarketplace(
        activeId,
        Number(pushWarehouseId),
        pushMode,
      )
      setSuccess(result.message)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка выгрузки')
    } finally {
      setLoading(false)
    }
  }

  async function handleComplete() {
    if (!activeId) return
    if (!window.confirm('Завершить приёмку? Сканирование будет закрыто.')) return
    setLoading(true)
    setError('')
    try {
      const next = await completeArticleIntakeSession(activeId)
      setSession(next)
      setSuccess('Приёмка завершена')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка')
    } finally {
      setLoading(false)
    }
  }

  const warehouses = isOzon ? ozonWarehouses : wbWarehouses.filter((wh) => wh.is_enabled)

  if (!activeId) {
    return (
      <div className="page">
        <header className="page__header">
          <div>
            <h1>Приёмка с ячейками по артикулам</h1>
            <p>
              Скан баркода → все размеры артикула и цвета из {mpName} → ячейки по EU · остатки сначала в CRM
            </p>
          </div>
          <Link to="/warehouse" className="btn btn--secondary">← Склад</Link>
        </header>

        {error && <div className="alert alert--error">{error}</div>}

        <div className="art-home">
          <section className="art-card">
            <h2>Новая приёмка</h2>
            <label className="art-field">
              Клиент (если уже есть)
              <select
                value={existingSellerId}
                onChange={(e) => setExistingSellerId(e.target.value ? Number(e.target.value) : '')}
              >
                <option value="">— новый селлер —</option>
                {sellers.map((s) => (
                  <option key={s.id} value={s.id}>{s.company_name}</option>
                ))}
              </select>
            </label>
            {!existingSellerId && (
              <label className="art-field">
                Название ИП / компании
                <input value={companyName} onChange={(e) => setCompanyName(e.target.value)} />
              </label>
            )}
            <button type="button" className="btn btn--primary" disabled={loading} onClick={() => void startNew()}>
              Начать
            </button>
          </section>

          <section className="art-card">
            <h2>Недавние</h2>
            {sessions.length === 0 ? (
              <p className="art-muted">Пока нет сессий</p>
            ) : (
              <ul>
                {sessions.slice(0, 12).map((item) => (
                  <li key={item.id}>
                    <Link to={`/intake-article/${item.id}`}>
                      #{item.id} · {item.seller_name} · {STATUS_LABEL[item.status]} · {item.total_units} шт.
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>
    )
  }

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h1>Приёмка #{activeId}</h1>
          <p>{session?.seller_name} · {session ? STATUS_LABEL[session.status] : '…'}</p>
        </div>
        <Link to="/intake-article" className="btn btn--secondary">← Список</Link>
      </header>

      {error && <div className="alert alert--error">{error}</div>}
      {success && <div className="alert alert--success">{success}</div>}

      {session && (
        <>
          <section className="art-card art-scan">
            <div className="art-stats">
              <span>Групп: <strong>{session.confirmed_groups_count}</strong></span>
              <span>Товаров: <strong>{session.products_count}</strong></span>
              <span>Принято: <strong>{session.total_units} шт.</strong></span>
              <span>Сканов: <strong>{session.scan_count}</strong></span>
            </div>

            {canScan ? (
              <form onSubmit={(e) => void handleScan(e)}>
                <div className="art-scan-row">
                  <label className="art-field">
                    Баркод
                    <input
                      ref={barcodeRef}
                      value={barcode}
                      onChange={(e) => setBarcode(e.target.value)}
                      onKeyDown={onBarcodeKeyDown}
                      autoComplete="off"
                    />
                  </label>
                  <label className="art-field">
                    Кол-во
                    <input
                      type="number"
                      min={0}
                      value={quantityInput}
                      onChange={(e) => setQuantityInput(e.target.value)}
                    />
                  </label>
                  <button type="submit" className="btn btn--primary" disabled={loading}>
                    Скан
                  </button>
                </div>
                <p className="art-muted">
                  Новый артикул+цвет — покажем все размеры для подтверждения ячеек. Тот же артикул — только +остаток.
                </p>
              </form>
            ) : (
              <p className="art-muted">Сканирование закрыто</p>
            )}

            {session.confirmed_groups_count > 0 && (
              <div className="art-push">
                <h3>Выгрузка на {mpName}</h3>
                <p className="art-muted">Остатки из CRM → маркетплейс (можно до или после завершения)</p>
                <div className="art-push-grid">
                  <label className="art-field">
                    FBS-склад
                    <select
                      value={pushWarehouseId}
                      onChange={(e) => setPushWarehouseId(e.target.value ? Number(e.target.value) : '')}
                    >
                      <option value="">— выберите —</option>
                      {warehouses.map((wh) => (
                        <option key={wh.id} value={wh.id}>
                          {wh.name || `Склад #${isOzon ? (wh as SellerOzonWarehouse).ozon_warehouse_id : (wh as SellerWarehouse).wb_warehouse_id}`}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="art-field">
                    Режим
                    <select
                      value={pushMode}
                      onChange={(e) => setPushMode(e.target.value as 'replace' | 'add')}
                    >
                      <option value="replace">Заменить на наши остатки</option>
                      <option value="add">Прибавить к маркетплейсу</option>
                    </select>
                  </label>
                  <button
                    type="button"
                    className="btn btn--secondary"
                    disabled={loading || !pushWarehouseId}
                    onClick={() => void handlePush()}
                  >
                    Выгрузить
                  </button>
                </div>
              </div>
            )}

            {canScan && session.confirmed_groups_count > 0 && (
              <div style={{ marginTop: '1rem' }}>
                <button
                  type="button"
                  className="btn btn--secondary"
                  disabled={loading}
                  onClick={() => void handleComplete()}
                >
                  Завершить приёмку
                </button>
              </div>
            )}
          </section>
        </>
      )}

      {preview && (
        <div className="art-modal-backdrop" role="presentation">
          <div className="art-modal" role="dialog" aria-modal="true">
            <h2>Новая группа: артикул + цвет</h2>
            <p className="art-modal__meta">
              Артикул <strong>{preview.article_label || preview.vendor_code || preview.article_id}</strong>
              {' · '}цвет <strong>{preview.color_label}</strong>
              {' · '}размеров: <strong>{preview.group_size ?? previewItems.filter((i) => !i.excluded).length}</strong>
            </p>
            <p className="art-modal__meta">{preview.title}</p>
            <table className="art-modal__table">
              <thead>
                <tr>
                  <th>Артикул</th>
                  <th>Цвет</th>
                  <th>Размер</th>
                  <th>Баркод</th>
                  <th>Ячейка</th>
                  <th>Кол-во</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {previewItems.map((item) => (
                  <tr
                    key={item.barcode}
                    className={item.excluded ? 'art-row--excluded' : ''}
                  >
                    <td>{item.vendor_code || item.article_label || '—'}</td>
                    <td>{item.color_label || preview.color_label || '—'}</td>
                    <td>{item.size_label}</td>
                    <td><code>{item.barcode}</code></td>
                    <td>{item.excluded ? '—' : `№ ${item.cell_number}`}</td>
                    <td>{item.quantity > 0 ? item.quantity : 0}</td>
                    <td>
                      {item.barcode !== preview.scanned_barcode && !item.already_in_crm && (
                        <button
                          type="button"
                          className="btn btn--secondary btn--small"
                          onClick={() => toggleExcludeItem(item.barcode)}
                        >
                          {item.excluded ? 'Вернуть' : 'Удалить ячейку'}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="art-modal__actions">
              <button
                type="button"
                className="btn btn--secondary"
                disabled={loading}
                onClick={() => {
                  setPreview(null)
                  setPreviewItems([])
                  focusBarcode()
                }}
              >
                Отмена
              </button>
              <button
                type="button"
                className="btn btn--primary"
                disabled={loading}
                onClick={() => void handleConfirmGroup()}
              >
                Создать ячейки
              </button>
            </div>
          </div>
        </div>
      )}

      {loading && !session && <p>Загрузка…</p>}
    </div>
  )
}
