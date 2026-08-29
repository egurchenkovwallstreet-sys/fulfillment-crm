import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  completeArticleIntakeSession,
  confirmArticleGroup,
  createArticleIntakeSession,
  deleteArticleIntakeProduct,
  fetchArticleIntakeSession,
  fetchArticleIntakeSessions,
  incrementArticleIntake,
  pushArticleIntakeToMarketplace,
  saveArticleGroupQuantities,
  scanArticleIntake,
  type ArticleGroupPreview,
  type ArticleGroupPreviewItem,
  type ArticleIntakeProduct,
  type ArticleIntakeSession,
} from '../api/articleIntake'
import { fetchProductCellLabel, fetchSellers, type Seller } from '../api/warehouse'
import { fetchSellerOzonWarehouses, fetchSellerWarehouses, type SellerOzonWarehouse, type SellerWarehouse } from '../api/sellers'
import { CrmResultModal, type CrmResultModalState } from '../components/CrmResultModal'
import { printCellLabel } from '../utils/cellLabelPrint'
import { useMarketplace } from '../context/MarketplaceContext'
import './ArticleIntakePage.css'

const STATUS_LABEL: Record<ArticleIntakeSession['status'], string> = {
  active: 'Приёмка',
  completed: 'Завершена',
}

function groupKeys(session: ArticleIntakeSession | null): string[] {
  if (!session?.products?.length) return []
  return [...new Set(session.products.map((p) => p.article_group_key).filter(Boolean))]
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
  const [wbWarehouses, setWbWarehouses] = useState<SellerWarehouse[]>([])
  const [ozonWarehouses, setOzonWarehouses] = useState<SellerOzonWarehouse[]>([])
  const [pushWarehouseId, setPushWarehouseId] = useState<number | ''>('')
  const [pushMode, setPushMode] = useState<'replace' | 'add'>('replace')
  const [preview, setPreview] = useState<ArticleGroupPreview | null>(null)
  const [previewItems, setPreviewItems] = useState<ArticleGroupPreviewItem[]>([])
  const [zoomPhotoUrl, setZoomPhotoUrl] = useState<string | null>(null)
  const [activeGroupKey, setActiveGroupKey] = useState('')
  const [entryMode, setEntryMode] = useState<'piece' | 'manual'>('piece')
  const [qtyDraft, setQtyDraft] = useState<Record<string, string>>({})
  const [cellHit, setCellHit] = useState<ArticleIntakeProduct | null>(null)
  const [resultModal, setResultModal] = useState<CrmResultModalState | null>(null)
  const [loading, setLoading] = useState(false)

  const activeId = sessionId ? Number(sessionId) : null
  const canEdit = session?.can_edit ?? false
  const locked = Boolean(session?.marketplace_pushed_at)
  const groups = useMemo(() => groupKeys(session), [session])

  const activeProducts = useMemo(
    () => (session?.products || []).filter((p) => p.article_group_key === activeGroupKey),
    [session?.products, activeGroupKey],
  )

  const focusBarcode = useCallback(() => {
    window.setTimeout(() => barcodeRef.current?.focus(), 20)
  }, [])

  const syncQtyDraft = useCallback((products: ArticleIntakeProduct[], groupKey: string) => {
    const next: Record<string, string> = {}
    for (const p of products) {
      if (p.article_group_key === groupKey) {
        next[p.barcode] = String(p.quantity ?? 0)
      }
    }
    setQtyDraft(next)
  }, [])

  const applySession = useCallback(
    (next: ArticleIntakeSession) => {
      setSession(next)
      const key = next.active_group_key || groupKeys(next)[0] || ''
      setActiveGroupKey(key)
      if (key && next.products) {
        syncQtyDraft(next.products, key)
      }
    },
    [syncQtyDraft],
  )

  const loadHome = useCallback(async () => {
    try {
      const [list, sellerList] = await Promise.all([fetchArticleIntakeSessions(), fetchSellers()])
      setSessions(list)
      setSellers(sellerList)
    } catch (err) {
      setResultModal({
        kind: 'error',
        title: 'Ошибка',
        message: err instanceof Error ? err.message : 'Не удалось загрузить список',
      })
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
      .then(applySession)
      .catch((err) =>
        setResultModal({
          kind: 'error',
          title: 'Ошибка',
          message: err instanceof Error ? err.message : 'Сессия не найдена',
        }),
      )
      .finally(() => setLoading(false))
  }, [activeId, applySession, loadHome])

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
    if (canEdit) focusBarcode()
  }, [canEdit, focusBarcode, session?.id, activeGroupKey, entryMode])

  useEffect(() => {
    if (activeGroupKey && session?.products) {
      syncQtyDraft(session.products, activeGroupKey)
    }
  }, [activeGroupKey, session?.products, syncQtyDraft])

  async function startNew() {
    const name = companyName.trim()
    if (!name && !existingSellerId) {
      setResultModal({ kind: 'error', title: 'Ошибка', message: 'Укажите название ИП или выберите клиента' })
      return
    }
    setLoading(true)
    try {
      const created = existingSellerId
        ? await createArticleIntakeSession({ seller_id: Number(existingSellerId) })
        : await createArticleIntakeSession({ company_name: name })
      navigate(`/intake-article/${created.id}`)
    } catch (err) {
      setResultModal({
        kind: 'error',
        title: 'Ошибка',
        message: err instanceof Error ? err.message : 'Не удалось начать приёмку',
      })
    } finally {
      setLoading(false)
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
    setLoading(true)
    try {
      const inSession = session?.products?.some((p) => p.barcode === value)
      if (entryMode === 'piece' && inSession) {
        const result = await incrementArticleIntake(activeId, value)
        applySession(result.session)
        setCellHit(result.product)
        setBarcode('')
        return
      }

      const result = await scanArticleIntake(activeId, value, { scan_mode: 'lookup' })
      applySession(result.session)
      setBarcode('')

      if (result.action === 'preview') {
        setPreview(result.preview)
        setPreviewItems(result.preview.items.map((item) => ({ ...item })))
        return
      }
      if (result.action === 'incremented' || result.action === 'added') {
        setCellHit(result.product)
        return
      }
      if (result.action === 'known') {
        setCellHit(result.product)
        setActiveGroupKey(result.product.article_group_key)
      }
    } catch (err) {
      setResultModal({
        kind: 'error',
        title: 'Ошибка скана',
        message: err instanceof Error ? err.message : 'Скан не принят',
      })
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
      if (!window.confirm(`Удалить ячейку для размера ${label}?\n\nРазмер не будет создан в CRM.`)) {
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
      setResultModal({ kind: 'error', title: 'Ошибка', message: 'Оставьте хотя бы один размер' })
      return
    }
    setLoading(true)
    try {
      const result = await confirmArticleGroup(activeId, {
        scanned_barcode: preview.scanned_barcode,
        items: previewItems.map((item) => ({
          barcode: item.barcode,
          cell_number: item.cell_number,
          excluded: item.excluded,
        })),
      })
      applySession(result.session)
      setPreview(null)
      setPreviewItems([])
      setActiveGroupKey(result.group_key)
      setResultModal({
        kind: 'success',
        title: 'Ячейки созданы',
        message: `Создано ${result.created_products} ячеек.\nТеперь внесите остатки по размерам.`,
      })
      focusBarcode()
    } catch (err) {
      setResultModal({
        kind: 'error',
        title: 'Ошибка',
        message: err instanceof Error ? err.message : 'Не удалось создать ячейки',
      })
    } finally {
      setLoading(false)
    }
  }

  async function handleSaveQuantities() {
    if (!activeId || !activeGroupKey || !canEdit) return
    const items = activeProducts.map((p) => ({
      barcode: p.barcode,
      quantity: Math.max(0, parseInt(qtyDraft[p.barcode] || '0', 10) || 0),
    }))
    setLoading(true)
    try {
      const result = await saveArticleGroupQuantities(activeId, activeGroupKey, items)
      applySession(result.session)
      setResultModal({
        kind: 'success',
        title: 'Остатки сохранены',
        message: `Группа сохранена.\nОбновлено позиций: ${result.updated}`,
      })
    } catch (err) {
      setResultModal({
        kind: 'error',
        title: 'Ошибка',
        message: err instanceof Error ? err.message : 'Не удалось сохранить остатки',
      })
    } finally {
      setLoading(false)
    }
  }

  async function handleDeleteProduct(product: ArticleIntakeProduct) {
    if (!activeId || !canEdit) return
    if (
      !window.confirm(
        `Удалить баркод ${product.barcode}?\n\nЯчейка №${product.cell_number} и количество будут удалены.`,
      )
    ) {
      return
    }
    setLoading(true)
    try {
      const result = await deleteArticleIntakeProduct(activeId, product.id)
      applySession(result.session)
      setResultModal({
        kind: 'success',
        title: 'Удалено',
        message: `Баркод ${product.barcode} и ячейка №${product.cell_number} удалены.`,
      })
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

  async function handlePrintLabel(product: ArticleIntakeProduct) {
    try {
      const label = await fetchProductCellLabel(product.id)
      printCellLabel(label, true)
    } catch (err) {
      setResultModal({
        kind: 'error',
        title: 'Печать',
        message: err instanceof Error ? err.message : 'Не удалось получить этикетку',
      })
    }
  }

  async function handlePush() {
    if (!activeId || !pushWarehouseId) {
      setResultModal({ kind: 'error', title: 'Ошибка', message: 'Выберите склад для выгрузки' })
      return
    }
    const modeLabel = pushMode === 'replace' ? 'заменить остатки в ЛК' : 'прибавить к остаткам в ЛК'
    if (!window.confirm(`Выгрузить остатки из CRM на ${mpName} (${modeLabel})?`)) return
    setLoading(true)
    try {
      const result = await pushArticleIntakeToMarketplace(activeId, Number(pushWarehouseId), pushMode)
      applySession(result.session)
      if (result.error_count > 0) {
        setResultModal({
          kind: 'error',
          title: 'Выгрузка с ошибками',
          message: `${result.message}\n\nПроверьте ошибки в журнале.`,
        })
      } else {
        setResultModal({
          kind: 'success',
          title: 'Выгрузка выполнена',
          message: result.message + (result.locked ? '\n\nПриёмка заблокирована для редактирования.' : ''),
        })
      }
    } catch (err) {
      setResultModal({
        kind: 'error',
        title: 'Ошибка выгрузки',
        message: err instanceof Error ? err.message : 'Не удалось выгрузить',
      })
    } finally {
      setLoading(false)
    }
  }

  async function handleComplete() {
    if (!activeId) return
    if (!window.confirm('Завершить приёмку?')) return
    setLoading(true)
    try {
      const next = await completeArticleIntakeSession(activeId)
      applySession(next)
      setResultModal({ kind: 'success', title: 'Готово', message: 'Приёмка завершена.' })
    } catch (err) {
      setResultModal({
        kind: 'error',
        title: 'Ошибка',
        message: err instanceof Error ? err.message : 'Не удалось завершить',
      })
    } finally {
      setLoading(false)
    }
  }

  const warehouses = isOzon ? ozonWarehouses : wbWarehouses

  if (!activeId) {
    return (
      <div className="page">
        <header className="page__header">
          <div>
            <h1>Приёмка с ячейками по артикулам</h1>
            <p>Скан → проверка артикула и цвета → ячейки → остатки на фулфилменте → выгрузка на {mpName}</p>
          </div>
          <Link to="/warehouse" className="btn btn--secondary">← Склад</Link>
        </header>

        <div className="art-home">
          <section className="art-card">
            <h2>Новая приёмка</h2>
            <div className="crm-selector-stack">
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
            </div>
            <div className="art-card__actions">
              <button type="button" className="btn btn--primary" disabled={loading} onClick={() => void startNew()}>
                Начать
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
                  <li key={item.id}>
                    <Link to={`/intake-article/${item.id}`}>
                      #{item.id} · {item.seller_name} · {STATUS_LABEL[item.status]}
                      {item.marketplace_pushed_at ? ' · выгружено' : ' · продолжить'}
                      {' · '}{item.total_units} шт.
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>

        {resultModal && <CrmResultModal modal={resultModal} onClose={() => setResultModal(null)} />}
      </div>
    )
  }

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h1>Приёмка #{activeId}</h1>
          <p>
            {session?.seller_name} · {session ? STATUS_LABEL[session.status] : '…'}
            {locked ? ' · заблокировано после выгрузки' : ''}
          </p>
        </div>
        <Link to="/intake-article" className="btn btn--secondary">← Список</Link>
      </header>

      {session && (
        <>
          <section className="art-card art-scan">
            <div className="art-stats">
              <span>Групп: <strong>{session.confirmed_groups_count}</strong></span>
              <span>Товаров: <strong>{session.products_count}</strong></span>
              <span>На складе: <strong>{session.total_units} шт.</strong></span>
            </div>

            {canEdit ? (
              <>
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
                    <div className="art-field art-field--mode">
                      <span className="art-field__label">Ввод остатков</span>
                      <div className="art-mode-toggle">
                        <button
                          type="button"
                          className={`btn btn--small${entryMode === 'piece' ? ' btn--primary' : ' btn--secondary'}`}
                          onClick={() => setEntryMode('piece')}
                        >
                          По 1 (скан)
                        </button>
                        <button
                          type="button"
                          className={`btn btn--small${entryMode === 'manual' ? ' btn--primary' : ' btn--secondary'}`}
                          onClick={() => setEntryMode('manual')}
                        >
                          Числом
                        </button>
                      </div>
                    </div>
                    <button type="submit" className="btn btn--primary art-scan-row__submit" disabled={loading}>
                      {entryMode === 'piece' && activeProducts.length > 0 ? '+1 скан' : 'Проверить'}
                    </button>
                  </div>
                  <p className="art-muted">
                    Новый цвет — проверка группы и создание ячеек. После ячеек — скан +1 или ручной ввод, затем «Сохранить количество».
                  </p>
                </form>

                {groups.length > 0 && (
                  <div className="art-qty-panel">
                    <div className="art-qty-panel__head">
                      <label className="art-field art-field--inline">
                        Цвет / группа
                        <select
                          value={activeGroupKey}
                          onChange={(e) => setActiveGroupKey(e.target.value)}
                        >
                          {groups.map((key) => (
                            <option key={key} value={key}>{key.replace(/^ozon:\d+:/, '')}</option>
                          ))}
                        </select>
                      </label>
                      <button
                        type="button"
                        className="btn btn--primary"
                        disabled={loading || !activeGroupKey}
                        onClick={() => void handleSaveQuantities()}
                      >
                        Сохранить количество
                      </button>
                    </div>
                    <table className="art-modal__table">
                      <thead>
                        <tr>
                          <th>Размер</th>
                          <th>Баркод</th>
                          <th>Ячейка</th>
                          <th>Кол-во</th>
                          <th />
                        </tr>
                      </thead>
                      <tbody>
                        {activeProducts.map((product) => (
                          <tr key={product.id}>
                            <td>{product.tech_size || '—'}</td>
                            <td><code>{product.barcode}</code></td>
                            <td>№ {product.cell_number}</td>
                            <td>
                              {entryMode === 'manual' ? (
                                <input
                                  className="art-qty-input"
                                  type="number"
                                  min={0}
                                  value={qtyDraft[product.barcode] ?? '0'}
                                  onChange={(e) =>
                                    setQtyDraft((prev) => ({ ...prev, [product.barcode]: e.target.value }))
                                  }
                                />
                              ) : (
                                product.quantity
                              )}
                            </td>
                            <td className="art-row-actions">
                              <button
                                type="button"
                                className="btn btn--secondary btn--small"
                                onClick={() => void handlePrintLabel(product)}
                              >
                                Этикетка
                              </button>
                              <button
                                type="button"
                                className="btn btn--danger-outline btn--small"
                                onClick={() => void handleDeleteProduct(product)}
                              >
                                Удалить
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </>
            ) : (
              <p className="art-muted">
                {locked
                  ? 'Редактирование закрыто после выгрузки на маркетплейс.'
                  : 'Сканирование закрыто.'}
              </p>
            )}

            {session.can_push && session.confirmed_groups_count > 0 && (
              <div className="art-push">
                <h3>Выгрузка на {mpName}</h3>
                <div className="crm-selector-row art-push-grid">
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
                      <option value="replace">Заменить на остатки CRM</option>
                      <option value="add">Прибавить к ЛК</option>
                    </select>
                  </label>
                  <button
                    type="button"
                    className="btn btn--secondary art-push-grid__btn"
                    disabled={loading || !pushWarehouseId}
                    onClick={() => void handlePush()}
                  >
                    Выгрузить
                  </button>
                </div>
              </div>
            )}

            {canEdit && session.confirmed_groups_count > 0 && (
              <div className="art-card__actions">
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
            <div className="art-modal__head">
              <div className="art-modal__head-text">
                <h2>Проверка: артикул + цвет</h2>
                <p className="art-modal__meta">
                  Артикул <strong>{preview.article_label || preview.vendor_code}</strong>
                  {' · '}цвет <strong>{preview.color_label}</strong>
                  {' · '}размеров:{' '}
                  <strong>{previewItems.filter((i) => !i.excluded).length}</strong>
                </p>
                <p className="art-modal__meta">{preview.title}</p>
              </div>
              {(preview.photo_url || previewItems.find((i) => i.barcode === preview.scanned_barcode)?.photo_url) && (
                <button
                  type="button"
                  className="art-modal__photo-btn"
                  title="Увеличить фото"
                  onClick={() =>
                    setZoomPhotoUrl(
                      preview.photo_url ||
                        previewItems.find((i) => i.barcode === preview.scanned_barcode)?.photo_url ||
                        null,
                    )
                  }
                >
                  <img
                    src={
                      preview.photo_url ||
                      previewItems.find((i) => i.barcode === preview.scanned_barcode)?.photo_url
                    }
                    alt=""
                    className="art-modal__photo"
                  />
                </button>
              )}
            </div>
            <table className="art-modal__table">
              <thead>
                <tr>
                  <th>Артикул</th>
                  <th>Цвет</th>
                  <th>Размер</th>
                  <th>Баркод</th>
                  <th>Ячейка</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {previewItems.map((item) => {
                  const isScanned = item.barcode === preview.scanned_barcode
                  const rowClass = [
                    item.excluded ? 'art-row--excluded' : '',
                    isScanned ? 'art-row--scanned' : '',
                  ]
                    .filter(Boolean)
                    .join(' ')
                  return (
                    <tr key={item.barcode} className={rowClass || undefined}>
                      <td>{item.vendor_code || item.article_label || '—'}</td>
                      <td>{item.color_label || preview.color_label || '—'}</td>
                      <td>{item.size_label}</td>
                      <td><code>{item.barcode}</code></td>
                      <td>{item.excluded ? '—' : `№ ${item.cell_number}`}</td>
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
                  )
                })}
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
                Сохранить ячейки
              </button>
            </div>
          </div>
        </div>
      )}

      {cellHit && (
        <div className="art-cell-hit-backdrop" onClick={() => setCellHit(null)} role="presentation">
          <div className="art-cell-hit" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
            <p className="art-cell-hit__label">Ячейка</p>
            <p className="art-cell-hit__number">№ {cellHit.cell_number}</p>
            <p className="art-cell-hit__meta">
              {cellHit.tech_size || '—'} · <code>{cellHit.barcode}</code>
            </p>
            <p className="art-cell-hit__qty">Количество: <strong>{cellHit.quantity}</strong></p>
            <button type="button" className="btn btn--primary" onClick={() => setCellHit(null)}>
              Понятно
            </button>
          </div>
        </div>
      )}

      {zoomPhotoUrl && (
        <div
          className="art-photo-zoom"
          role="dialog"
          aria-modal="true"
          aria-label="Фото товара"
          onClick={() => setZoomPhotoUrl(null)}
        >
          <button type="button" className="art-photo-zoom__close" onClick={() => setZoomPhotoUrl(null)}>✕</button>
          <img
            src={zoomPhotoUrl}
            alt="Фото товара"
            className="art-photo-zoom__img"
            onClick={(e) => e.stopPropagation()}
          />
        </div>
      )}

      {resultModal && <CrmResultModal modal={resultModal} onClose={() => setResultModal(null)} />}

      {loading && !session && <p>Загрузка…</p>}
    </div>
  )
}
