import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchSellers } from '../api/warehouse'
import {
  confirmOnboarding,
  fetchOnboardingPreview,
  fetchStockOverview,
  transferStock,
  type OnboardingItem,
  type OnboardingPreview,
  type StockOverview,
  type StockOverviewProduct,
} from '../api/warehouseHub'
import { syncSellerWarehouses } from '../api/sellers'
import './WarehouseHubPage.css'

type TabId = 'onboarding' | 'intake' | 'transfer'

function PhotoThumb({ url, alt }: { url: string; alt: string }) {
  const [zoomed, setZoomed] = useState(false)
  if (!url) {
    return <span className="whub-photo whub-photo--empty">—</span>
  }
  return (
    <>
      <button
        type="button"
        className="whub-photo-btn"
        onClick={() => setZoomed(true)}
        aria-label="Увеличить фото"
      >
        <img src={url} alt={alt} className="whub-photo" />
      </button>
      {zoomed && (
        <div
          className="whub-photo-zoom-backdrop"
          role="presentation"
          onClick={() => setZoomed(false)}
        >
          <img src={url} alt={alt} className="whub-photo-zoom" onClick={() => setZoomed(false)} />
        </div>
      )}
    </>
  )
}

export function WarehouseHubPage() {
  const [tab, setTab] = useState<TabId>('onboarding')
  const [sellers, setSellers] = useState<Seller[]>([])
  const [sellerId, setSellerId] = useState<number | ''>('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  const [preview, setPreview] = useState<OnboardingPreview | null>(null)
  const [excludeBarcodes, setExcludeBarcodes] = useState<Set<string>>(new Set())
  const [excludeNmIds, setExcludeNmIds] = useState<Set<number>>(new Set())

  const [stockOverview, setStockOverview] = useState<StockOverview | null>(null)
  const [transferProduct, setTransferProduct] = useState<StockOverviewProduct | null>(null)
  const [fromWh, setFromWh] = useState<number | ''>('')
  const [toWh, setToWh] = useState<number | ''>('')
  const [transferQty, setTransferQty] = useState(1)

  useEffect(() => {
    fetchSellers()
      .then((data) => {
        setSellers(data)
        if (data.length === 1) setSellerId(data[0].id)
      })
      .catch((err) => setError(err instanceof Error ? err.message : 'Ошибка'))
  }, [])

  const activeItems = useMemo(() => {
    if (!preview) return []
    return preview.items.map((item) => ({
      ...item,
      excluded: excludeBarcodes.has(item.barcode) || excludeNmIds.has(item.wb_nm_id),
    }))
  }, [preview, excludeBarcodes, excludeNmIds])

  const visibleArticles = useMemo(() => {
    if (!preview) return []
    return preview.articles
      .map((article) => ({
        ...article,
        items: article.items.map((item) => ({
          ...item,
          excluded: excludeBarcodes.has(item.barcode) || excludeNmIds.has(item.wb_nm_id),
        })),
      }))
      .filter((article) => !excludeNmIds.has(article.wb_nm_id))
      .map((article) => ({
        ...article,
        items: article.items.filter((item) => !excludeBarcodes.has(item.barcode)),
      }))
      .filter((article) => article.items.length > 0)
  }, [preview, excludeBarcodes, excludeNmIds])

  const renumberedItems = useMemo(() => {
    let num = 1
    return activeItems.map((item) => {
      if (item.excluded || item.already_in_crm) {
        return { ...item, cell_number: item.already_in_crm ? item.cell_number : '' }
      }
      const next = { ...item, cell_number: String(num) }
      num += 1
      return next
    })
  }, [activeItems])

  const newToCreate = renumberedItems.filter((i) => !i.excluded && !i.already_in_crm)

  const handleLoadPreview = useCallback(async () => {
    if (!sellerId) return
    setLoading(true)
    setError('')
    setSuccess('')
    setExcludeBarcodes(new Set())
    setExcludeNmIds(new Set())
    try {
      if (sellers.length) {
        await syncSellerWarehouses(Number(sellerId))
      }
      const data = await fetchOnboardingPreview(Number(sellerId))
      setPreview(data)
      setSuccess(
        `Каталог: ${data.cards_count} карточек, ${data.barcodes_count} баркодов, новых: ${data.new_barcodes_count}`,
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка загрузки каталога')
      setPreview(null)
    } finally {
      setLoading(false)
    }
  }, [sellerId, sellers.length])

  const handleExcludeBarcode = (barcode: string) => {
    setExcludeBarcodes((prev) => new Set(prev).add(barcode))
  }

  const handleExcludeArticle = (nmId: number) => {
    setExcludeNmIds((prev) => new Set(prev).add(nmId))
  }

  const handleConfirmOnboarding = async () => {
    if (!sellerId || newToCreate.length === 0) return
    if (!window.confirm(
      `Создать ${newToCreate.length} товаров с ячейками и остатками из WB?\n\nУже в CRM: ${preview?.existing_barcodes_count ?? 0} баркодов будут пропущены.`,
    )) return
    setLoading(true)
    setError('')
    try {
      const result = await confirmOnboarding(Number(sellerId), renumberedItems)
      setSuccess(`Создано товаров: ${result.created_products}, пропущено: ${result.skipped}`)
      await handleLoadPreview()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка подтверждения')
    } finally {
      setLoading(false)
    }
  }

  const handleLoadStockOverview = useCallback(async () => {
    if (!sellerId) return
    setLoading(true)
    setError('')
    try {
      setStockOverview(await fetchStockOverview(Number(sellerId)))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка загрузки остатков')
    } finally {
      setLoading(false)
    }
  }, [sellerId])

  useEffect(() => {
    if (tab === 'transfer' && sellerId) {
      void handleLoadStockOverview()
    }
  }, [tab, sellerId, handleLoadStockOverview])

  async function handleTransferSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!sellerId || !transferProduct || !fromWh || !toWh) return
    setLoading(true)
    setError('')
    try {
      await transferStock(Number(sellerId), {
        product_id: transferProduct.product_id,
        from_warehouse_id: Number(fromWh),
        to_warehouse_id: Number(toWh),
        quantity: transferQty,
      })
      setSuccess(`Перенесено ${transferQty} шт. Сумма по складам не изменилась.`)
      setTransferProduct(null)
      await handleLoadStockOverview()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка переноса')
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <header className="topbar">
        <div>
          <h1>Склад</h1>
          <p>Подключение селлера, приёмка и перераспределение остатков FBS</p>
        </div>
      </header>

      <div className="whub-tabs">
        <button
          type="button"
          className={`whub-tab${tab === 'onboarding' ? ' whub-tab--active' : ''}`}
          onClick={() => setTab('onboarding')}
        >
          Подключение (WB → CRM)
        </button>
        <button
          type="button"
          className={`whub-tab${tab === 'intake' ? ' whub-tab--active' : ''}`}
          onClick={() => setTab('intake')}
        >
          Приёмка (новый клиент)
        </button>
        <button
          type="button"
          className={`whub-tab${tab === 'transfer' ? ' whub-tab--active' : ''}`}
          onClick={() => setTab('transfer')}
        >
          Перераспределение
        </button>
      </div>

      <section className="panel whub-seller-bar">
        <label>
          Селлер
          <select
            value={sellerId}
            onChange={(e) => {
              setSellerId(e.target.value ? Number(e.target.value) : '')
              setPreview(null)
              setStockOverview(null)
            }}
          >
            <option value="">— выберите —</option>
            {sellers.map((s) => (
              <option key={s.id} value={s.id}>{s.company_name}</option>
            ))}
          </select>
        </label>
      </section>

      {error && <div className="alert alert--error">{error}</div>}
      {success && <div className="alert alert--success">{success}</div>}

      {tab === 'onboarding' && (
        <section className="panel">
          <p className="whub-hint">
            Сценарий 1: загрузка всего каталога WB, назначение ячеек по размерам, остатки суммируются
            по включённым FBS-складам. Удалите лишние баркоды или артикулы перед подтверждением.
          </p>
          <button
            type="button"
            className="btn btn--primary"
            disabled={!sellerId || loading}
            onClick={() => void handleLoadPreview()}
          >
            {loading ? 'Загрузка каталога WB…' : 'Загрузить каталог и остатки'}
          </button>

          {preview && (
            <>
              <div className="whub-stats">
                <span>Карточек: {preview.cards_count}</span>
                <span>Баркодов: {preview.barcodes_count}</span>
                <span>Новых: {newToCreate.length}</span>
                <span>Уже в CRM: {preview.existing_barcodes_count}</span>
                <span>Складов FBS: {preview.warehouses.length}</span>
              </div>

              <div className="whub-articles">
                {visibleArticles.map((article) => (
                  <article key={article.wb_nm_id} className="whub-article">
                    <header className="whub-article__head">
                      <PhotoThumb url={article.photo_url} alt={article.title} />
                      <div>
                        <h3>{article.title || `Артикул ${article.wb_nm_id}`}</h3>
                        <p>
                          WB #{article.wb_nm_id}
                          {article.vendor_code ? ` · ${article.vendor_code}` : ''}
                          {article.requires_marking ? ' · ЧЗ' : ''}
                        </p>
                        <button
                          type="button"
                          className="btn btn--small btn--secondary"
                          onClick={() => handleExcludeArticle(article.wb_nm_id)}
                        >
                          Удалить артикул
                        </button>
                      </div>
                    </header>
                    <table className="whub-table">
                      <thead>
                        <tr>
                          <th>Ячейка</th>
                          <th>Размер</th>
                          <th>Баркод</th>
                          <th>Остаток WB</th>
                          <th />
                        </tr>
                      </thead>
                      <tbody>
                        {article.items.map((item) => {
                          const row = renumberedItems.find((r) => r.barcode === item.barcode) || item
                          return (
                            <tr key={item.barcode} className={row.already_in_crm ? 'whub-row--crm' : ''}>
                              <td>{row.already_in_crm ? 'в CRM' : row.cell_number || '—'}</td>
                              <td>{item.size_label}</td>
                              <td><code>{item.barcode}</code></td>
                              <td>{item.wb_stock_total} шт.</td>
                              <td>
                                {!row.already_in_crm && (
                                  <button
                                    type="button"
                                    className="btn btn--small btn--secondary"
                                    onClick={() => handleExcludeBarcode(item.barcode)}
                                  >
                                    Убрать
                                  </button>
                                )}
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </article>
                ))}
              </div>

              <div className="whub-actions">
                <button
                  type="button"
                  className="btn btn--primary"
                  disabled={loading || newToCreate.length === 0}
                  onClick={() => void handleConfirmOnboarding()}
                >
                  Подтвердить ({newToCreate.length} товаров)
                </button>
              </div>
            </>
          )}
        </section>
      )}

      {tab === 'intake' && (
        <section className="panel">
          <p className="whub-hint">
            Сценарий 2: новый клиент с нулевыми остатками на FBS-складе. Физическая приёмка на фулфилменте
            → CRM выставляет остатки в WB.
          </p>
          <Link to="/intake" className="btn btn--primary">
            Открыть приёмку
          </Link>
        </section>
      )}

      {tab === 'transfer' && (
        <section className="panel">
          <p className="whub-hint">
            Перенос остатков между FBS-складами WB. Суммарный остаток баркода в CRM не меняется.
          </p>
          <button
            type="button"
            className="btn btn--secondary"
            disabled={!sellerId || loading}
            onClick={() => void handleLoadStockOverview()}
          >
            Обновить остатки из WB
          </button>

          {stockOverview && (
            <table className="whub-table whub-table--transfer">
              <thead>
                <tr>
                  <th>Ячейка</th>
                  <th>Товар</th>
                  <th>Баркод</th>
                  <th>Итого</th>
                  {stockOverview.warehouses.map((wh) => (
                    <th key={wh.id}>{wh.name}</th>
                  ))}
                  <th />
                </tr>
              </thead>
              <tbody>
                {stockOverview.products.map((product) => (
                  <tr key={product.product_id}>
                    <td>{product.cell_number}</td>
                    <td>
                      <div className="whub-product-cell">
                        <PhotoThumb url={product.photo_url} alt={product.name} />
                        <span>{product.name || '—'}</span>
                      </div>
                    </td>
                    <td><code>{product.barcode}</code></td>
                    <td><strong>{product.wb_total}</strong></td>
                    {stockOverview.warehouses.map((wh) => {
                      const row = product.by_warehouse.find((x) => x.warehouse_id === wh.id)
                      return <td key={wh.id}>{row?.quantity ?? 0}</td>
                    })}
                    <td>
                      <button
                        type="button"
                        className="btn btn--small btn--primary"
                        onClick={() => {
                          setTransferProduct(product)
                          setFromWh('')
                          setToWh('')
                          setTransferQty(1)
                        }}
                      >
                        Перенести
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {transferProduct && stockOverview && (
            <div className="whub-transfer-modal-backdrop" role="presentation" onClick={() => setTransferProduct(null)}>
              <form
                className="whub-transfer-modal panel"
                onSubmit={(e) => void handleTransferSubmit(e)}
                onClick={(e) => e.stopPropagation()}
              >
                <h3>Перераспределение</h3>
                <p><code>{transferProduct.barcode}</code> · яч. {transferProduct.cell_number}</p>
                <label>
                  Со склада
                  <select value={fromWh} onChange={(e) => setFromWh(e.target.value ? Number(e.target.value) : '')} required>
                    <option value="">—</option>
                    {stockOverview.warehouses.map((wh) => {
                      const qty = transferProduct.by_warehouse.find((x) => x.warehouse_id === wh.id)?.quantity ?? 0
                      return (
                        <option key={wh.id} value={wh.id} disabled={qty < 1}>
                          {wh.name} ({qty} шт.)
                        </option>
                      )
                    })}
                  </select>
                </label>
                <label>
                  На склад
                  <select value={toWh} onChange={(e) => setToWh(e.target.value ? Number(e.target.value) : '')} required>
                    <option value="">—</option>
                    {stockOverview.warehouses.map((wh) => (
                      <option key={wh.id} value={wh.id} disabled={wh.id === fromWh}>
                        {wh.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Количество
                  <input
                    type="number"
                    min={1}
                    value={transferQty}
                    onChange={(e) => setTransferQty(Number(e.target.value))}
                    required
                  />
                </label>
                <div className="whub-actions">
                  <button type="submit" className="btn btn--primary" disabled={loading}>
                    Перенести
                  </button>
                  <button type="button" className="btn btn--secondary" onClick={() => setTransferProduct(null)}>
                    Отмена
                  </button>
                </div>
              </form>
            </div>
          )}
        </section>
      )}
    </>
  )
}
