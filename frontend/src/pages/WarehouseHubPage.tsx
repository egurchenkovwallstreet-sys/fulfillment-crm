import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ProductPhotoThumb } from '../components/ProductPhotoThumb'
import { fetchSellers, type Seller } from '../api/warehouse'
import {
  applyStockImport,
  confirmOnboarding,
  fetchOnboardingPreview,
  fetchStockOverview,
  previewStockImport,
  transferStock,
  distributeStockEvenly,
  type OnboardingPreview,
  type StockImportPreview,
  type StockImportResult,
  type StockOverview,
  type StockOverviewProduct,
} from '../api/warehouseHub'
import {
  fetchSellerOzonWarehouses,
  fetchSellerWarehouses,
  syncSellerOzonWarehouses,
  syncSellerWarehouses,
  type SellerOzonWarehouse,
  type SellerWarehouse,
} from '../api/sellers'
import { useMarketplace } from '../context/MarketplaceContext'
import './WarehouseHubPage.css'

type TabId = 'onboarding' | 'import' | 'intake' | 'transfer'

type HubWarehouse = {
  id: number
  name: string
  code: number
  is_enabled: boolean
}

function mapWbWarehouses(rows: SellerWarehouse[]): HubWarehouse[] {
  return rows.map((wh) => ({
    id: wh.id,
    name: wh.name,
    code: wh.wb_warehouse_id,
    is_enabled: wh.is_enabled,
  }))
}

function mapOzonWarehouses(rows: SellerOzonWarehouse[]): HubWarehouse[] {
  return rows.map((wh) => ({
    id: wh.id,
    name: wh.name,
    code: wh.ozon_warehouse_id,
    is_enabled: wh.is_enabled,
  }))
}

export function WarehouseHubPage() {
  const { marketplace } = useMarketplace()
  const isOzon = marketplace === 'ozon'
  const mpName = isOzon ? 'Ozon' : 'WB'
  const [tab, setTab] = useState<TabId>('onboarding')
  const [sellers, setSellers] = useState<Seller[]>([])
  const [sellerId, setSellerId] = useState<number | ''>('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  const [preview, setPreview] = useState<OnboardingPreview | null>(null)
  const [sellerWarehouses, setSellerWarehouses] = useState<HubWarehouse[]>([])
  const [selectedWarehouseIds, setSelectedWarehouseIds] = useState<number[]>([])
  const [catalogMode, setCatalogMode] = useState<'all' | 'with_stock'>('all')
  const [excludeBarcodes, setExcludeBarcodes] = useState<Set<string>>(new Set())
  const [excludeNmIds, setExcludeNmIds] = useState<Set<number>>(new Set())

  const [stockOverview, setStockOverview] = useState<StockOverview | null>(null)
  const [transferProduct, setTransferProduct] = useState<StockOverviewProduct | null>(null)
  const [fromWh, setFromWh] = useState<number | ''>('')
  const [toWh, setToWh] = useState<number | ''>('')
  const [transferQty, setTransferQty] = useState(1)
  const [selectedDistributeIds, setSelectedDistributeIds] = useState<Set<number>>(new Set())

  const canDistributeEvenly = (stockOverview?.warehouses.length ?? 0) >= 2

  const distributableProducts = useMemo(
    () => stockOverview?.products.filter((product) => product.wb_total > 0) ?? [],
    [stockOverview],
  )

  const allDistributableSelected = useMemo(() => {
    if (distributableProducts.length === 0) return false
    return distributableProducts.every((product) => selectedDistributeIds.has(product.product_id))
  }, [distributableProducts, selectedDistributeIds])

  const [importWarehouseId, setImportWarehouseId] = useState<number | ''>('')
  const [importFile, setImportFile] = useState<File | null>(null)
  const [stockImportPreview, setStockImportPreview] = useState<StockImportPreview | null>(null)
  const [stockImportResult, setStockImportResult] = useState<StockImportResult | null>(null)

  useEffect(() => {
    fetchSellers()
      .then((data) => {
        setSellers(data)
        if (data.length === 1) setSellerId(data[0].id)
      })
      .catch((err) => setError(err instanceof Error ? err.message : 'Ошибка'))
  }, [])

  useEffect(() => {
    if (!sellerId) {
      setSellerWarehouses([])
      setSelectedWarehouseIds([])
      return
    }
    const load = isOzon ? fetchSellerOzonWarehouses : fetchSellerWarehouses
    load(Number(sellerId))
      .then((whs) => {
        const mapped = isOzon
          ? mapOzonWarehouses(whs as SellerOzonWarehouse[])
          : mapWbWarehouses(whs as SellerWarehouse[])
        setSellerWarehouses(mapped)
        setSelectedWarehouseIds(mapped.filter((w) => w.is_enabled).map((w) => w.id))
        if (mapped.length === 1) setImportWarehouseId(mapped[0].id)
      })
      .catch(() => setSellerWarehouses([]))
  }, [sellerId, isOzon])

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
    let num = preview?.next_cell_number ?? 1
    return activeItems.map((item) => {
      if (item.excluded || item.already_in_crm) {
        return { ...item, cell_number: item.already_in_crm ? item.cell_number : '' }
      }
      const next = { ...item, cell_number: String(num) }
      num += 1
      return next
    })
  }, [activeItems, preview?.next_cell_number])

  const newToCreate = renumberedItems.filter((i) => !i.excluded && !i.already_in_crm)

  const handleLoadPreview = useCallback(async () => {
    if (!sellerId) return
    if (selectedWarehouseIds.length === 0) {
      setError('Выберите хотя бы один FBS-склад')
      return
    }
    setLoading(true)
    setError('')
    setSuccess('')
    setExcludeBarcodes(new Set())
    setExcludeNmIds(new Set())
    try {
      if (isOzon) {
        await syncSellerOzonWarehouses(Number(sellerId))
        const whs = mapOzonWarehouses(await fetchSellerOzonWarehouses(Number(sellerId)))
        setSellerWarehouses(whs)
      } else {
        await syncSellerWarehouses(Number(sellerId))
        const whs = mapWbWarehouses(await fetchSellerWarehouses(Number(sellerId)))
        setSellerWarehouses(whs)
      }
      const data = await fetchOnboardingPreview(Number(sellerId), {
        catalog_mode: catalogMode,
        warehouse_ids: selectedWarehouseIds,
      })
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
  }, [sellerId, catalogMode, selectedWarehouseIds, isOzon])

  function toggleWarehouseSelection(warehouseId: number, checked: boolean) {
    setSelectedWarehouseIds((prev) => {
      if (checked) return [...prev, warehouseId]
      return prev.filter((id) => id !== warehouseId)
    })
  }

  async function handleStockImportPreview() {
    if (!sellerId || !importFile || !importWarehouseId) return
    setLoading(true)
    setError('')
    setSuccess('')
    setStockImportResult(null)
    setStockImportPreview(null)
    try {
      const data = await previewStockImport(Number(sellerId), Number(importWarehouseId), importFile)
      setStockImportPreview(data)
      const totals = data.totals
      let msg = `В файле: ${totals.file_barcodes} баркодов, ${totals.file_units} шт.`
      if (totals.to_apply > 0) {
        msg += `. К загрузке: ${totals.to_apply} баркодов (+${totals.add_units} шт.)`
      }
      if (totals.skipped_unknown > 0) {
        msg += `. Не в каталоге WB: ${totals.skipped_unknown} баркодов (${totals.skipped_units} шт.)`
      }
      setSuccess(msg)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка чтения файла')
    } finally {
      setLoading(false)
    }
  }

  function buildImportResultMessage(result: StockImportResult): string {
    const s = result.summary
    const lines = [
      `Было: CRM ${s.was_crm_units} шт., WB ${s.was_wb_units} шт.`,
      `Добавлено: +${s.added_units} шт. (${s.applied_barcodes} баркодов)`,
      `Получилось: CRM ${s.result_crm_units} шт., WB ${s.result_wb_units} шт.`,
      `Ожидалось: CRM ${s.expected_crm_units} шт., WB ${s.expected_wb_units} шт.`,
    ]
    if (result.created_products > 0) {
      lines.push(`Новых товаров в CRM: ${result.created_products}`)
    }
    if (result.ok) {
      lines.push('Сверка CRM и WB: всё совпало.')
    } else {
      lines.push(`Ошибок: ${s.failed_barcodes}. См. список баркодов ниже.`)
    }
    return lines.join('\n')
  }

  async function handleStockImportApply() {
    if (!sellerId || !stockImportPreview || !importWarehouseId) return
    setLoading(true)
    setError('')
    setSuccess('')
    setStockImportResult(null)
    try {
      const result = await applyStockImport(
        Number(sellerId),
        Number(importWarehouseId),
        stockImportPreview.rows,
      )
      setStockImportResult(result)
      const message = buildImportResultMessage(result)
      if (result.ok) {
        setSuccess(message)
        setStockImportPreview(null)
        setImportFile(null)
      } else {
        setError(message)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка применения')
    } finally {
      setLoading(false)
    }
  }

  const handleExcludeBarcode = (barcode: string) => {
    setExcludeBarcodes((prev) => new Set(prev).add(barcode))
  }

  const handleExcludeArticle = (nmId: number) => {
    setExcludeNmIds((prev) => new Set(prev).add(nmId))
  }

  const handleConfirmOnboarding = async () => {
    if (!sellerId || newToCreate.length === 0) return
    if (!window.confirm(
      `Создать ${newToCreate.length} товаров с ячейками ${mpName}?\n\nУже в CRM: ${preview?.existing_barcodes_count ?? 0} баркодов будут пропущены.`,
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

  useEffect(() => {
    setSelectedDistributeIds(new Set())
  }, [stockOverview])

  function toggleDistributeSelection(productId: number, checked: boolean) {
    setSelectedDistributeIds((prev) => {
      const next = new Set(prev)
      if (checked) next.add(productId)
      else next.delete(productId)
      return next
    })
  }

  function toggleSelectAllDistributable(checked: boolean) {
    if (!checked) {
      setSelectedDistributeIds(new Set())
      return
    }
    setSelectedDistributeIds(new Set(distributableProducts.map((product) => product.product_id)))
  }

  async function runDistributeEvenly(productIds?: number[]) {
    if (!sellerId || !canDistributeEvenly) return
    setLoading(true)
    setError('')
    setSuccess('')
    try {
      const result = await distributeStockEvenly(Number(sellerId), productIds)
      let msg = `Распределено: ${result.distributed}`
      if (result.skipped > 0) msg += `, пропущено: ${result.skipped}`
      if (result.errors.length > 0) msg += `, ошибок: ${result.errors.length}`
      setSuccess(msg)
      setSelectedDistributeIds(new Set())
      await handleLoadStockOverview()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка распределения')
    } finally {
      setLoading(false)
    }
  }

  function handleDistributeProduct(product: StockOverviewProduct) {
    if (!canDistributeEvenly || product.wb_total <= 0) return
    if (!window.confirm(
      `Равномерно распределить ${product.wb_total} шт. баркода ${product.barcode} по всем складам?`,
    )) return
    void runDistributeEvenly([product.product_id])
  }

  function handleDistributeSelected() {
    const ids = [...selectedDistributeIds]
    if (ids.length === 0) {
      setError('Отметьте товары галочкой')
      return
    }
    if (!window.confirm(`Равномерно распределить ${ids.length} выбранных товаров?`)) return
    void runDistributeEvenly(ids)
  }

  function handleDistributeAll() {
    if (!distributableProducts.length) {
      setError('Нет товаров с остатком для распределения')
      return
    }
    if (!window.confirm(
      `Равномерно распределить все ${distributableProducts.length} товаров с остатком?`,
    )) return
    void runDistributeEvenly()
  }

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
      <header className="topbar whub-header">
        <div>
          <h1>Склад</h1>
          <p>Подключение каталога {mpName}, приёмка и ячейки FBS</p>
        </div>
        <Link to="/inventory" className="btn btn--danger">
          Инвентаризация
        </Link>
      </header>

      <div className="whub-tabs">
        <button
          type="button"
          className={`whub-tab${tab === 'onboarding' ? ' whub-tab--active' : ''}`}
          onClick={() => setTab('onboarding')}
        >
          Подключение ({mpName} → CRM)
        </button>
        {!isOzon && (
          <button
            type="button"
            className={`whub-tab${tab === 'import' ? ' whub-tab--active' : ''}`}
            onClick={() => setTab('import')}
          >
            Импорт Excel
          </button>
        )}
        <button
          type="button"
          className={`whub-tab${tab === 'intake' ? ' whub-tab--active' : ''}`}
          onClick={() => setTab('intake')}
        >
          Приёмка (новый клиент)
        </button>
        {!isOzon && (
          <button
            type="button"
            className={`whub-tab${tab === 'transfer' ? ' whub-tab--active' : ''}`}
            onClick={() => setTab('transfer')}
          >
            Перераспределение
          </button>
        )}
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
              setStockImportPreview(null)
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
            Подключение каталога {mpName}: выберите склады FBS и режим загрузки. Ячейки назначаются на все
            размеры артикула (даже с нулевым остатком), если артикул попал в выборку.
            {isOzon ? ' Остатки пишутся в CRM; отдельная отправка на склад Ozon — следующей кнопкой.' : ''}
          </p>

          <div className="whub-options">
            <fieldset className="whub-fieldset">
              <legend>Режим каталога</legend>
              <label>
                <input
                  type="radio"
                  name="catalogMode"
                  checked={catalogMode === 'all'}
                  onChange={() => setCatalogMode('all')}
                />
                Все карточки со всеми баркодами
              </label>
              <label>
                <input
                  type="radio"
                  name="catalogMode"
                  checked={catalogMode === 'with_stock'}
                  onChange={() => setCatalogMode('with_stock')}
                />
                Только артикулы с остатком ≥ 1 на выбранных складах
              </label>
            </fieldset>

            <fieldset className="whub-fieldset">
              <legend>FBS-склады для остатков</legend>
              {sellerWarehouses.length === 0 ? (
                <p className="whub-hint">Загрузите склады {mpName} (кнопка ниже)</p>
              ) : (
                <ul className="whub-warehouse-picks">
                  {sellerWarehouses.map((wh) => (
                    <li key={wh.id}>
                      <label>
                        <input
                          type="checkbox"
                          checked={selectedWarehouseIds.includes(wh.id)}
                          onChange={(e) => toggleWarehouseSelection(wh.id, e.target.checked)}
                        />
                        {wh.name || `Склад #${wh.code}`}
                      </label>
                    </li>
                  ))}
                </ul>
              )}
            </fieldset>
          </div>

          <button
            type="button"
            className="btn btn--secondary btn--small"
            disabled={!sellerId || loading}
            onClick={() => {
              if (!sellerId) return
              const run = isOzon
                ? syncSellerOzonWarehouses(Number(sellerId)).then(() =>
                    fetchSellerOzonWarehouses(Number(sellerId)).then((rows) =>
                      setSellerWarehouses(mapOzonWarehouses(rows)),
                    ),
                  )
                : syncSellerWarehouses(Number(sellerId)).then(() =>
                    fetchSellerWarehouses(Number(sellerId)).then((rows) =>
                      setSellerWarehouses(mapWbWarehouses(rows)),
                    ),
                  )
              void run
            }}
          >
            Обновить склады из {mpName}
          </button>
          <button
            type="button"
            className="btn btn--primary"
            disabled={!sellerId || loading || selectedWarehouseIds.length === 0}
            onClick={() => void handleLoadPreview()}
          >
            {loading ? `Загрузка каталога ${mpName}…` : 'Подключение — загрузить каталог'}
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
                      <ProductPhotoThumb url={article.photo_url} alt={article.title} />
                      <div>
                        <h3>{article.title || `Артикул ${article.wb_nm_id}`}</h3>
                        <p>
                          {mpName} #{article.wb_nm_id}
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
                          <th>Остаток {mpName}</th>
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

      {tab === 'import' && !isOzon && (
        <section className="panel">
          <p className="whub-hint">
            Excel в формате WB (баркод + количество). Остатки <strong>прибавляются</strong> к CRM и
            выбранному FBS-складу в WB. Баркоды, которых нет в каталоге WB селлера, пропускаются.
          </p>
          <div className="whub-import-form">
            <label>
              FBS-склад
              <select
                value={importWarehouseId}
                onChange={(e) => setImportWarehouseId(e.target.value ? Number(e.target.value) : '')}
              >
                <option value="">— выберите —</option>
                {sellerWarehouses.map((wh) => (
                  <option key={wh.id} value={wh.id}>
                    {wh.name || `Склад #${wh.code}`}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Файл Excel
              <input
                type="file"
                accept=".xlsx,.xls"
                onChange={(e) => {
                  setImportFile(e.target.files?.[0] ?? null)
                  setStockImportPreview(null)
                  setStockImportResult(null)
                }}
              />
            </label>
            <button
              type="button"
              className="btn btn--primary"
              disabled={!sellerId || !importFile || !importWarehouseId || loading}
              onClick={() => void handleStockImportPreview()}
            >
              Предпросмотр
            </button>
          </div>

          {stockImportPreview && (
            <>
              <div className="whub-import-file-summary panel">
                <strong>Файл Excel</strong>
                <p>
                  {stockImportPreview.totals.file_barcodes} баркодов,{' '}
                  <strong>{stockImportPreview.totals.file_units} шт.</strong> всего
                </p>
              </div>

              <div className="whub-stats">
                <span>Склад: {stockImportPreview.warehouse.name}</span>
                <span>К применению: {stockImportPreview.totals.to_apply}</span>
                <span>+{stockImportPreview.totals.add_units} шт.</span>
                <span>Новых товаров: {stockImportPreview.totals.new_products}</span>
                {stockImportPreview.totals.skipped_unknown > 0 && (
                  <span className="whub-stat--warn">
                    Не в каталоге WB: {stockImportPreview.totals.skipped_unknown} (
                    {stockImportPreview.totals.skipped_units} шт.)
                  </span>
                )}
              </div>

              {stockImportPreview.skipped_unknown_details.length > 0 && (
                <details className="whub-skipped">
                  <summary>
                    Баркоды не найдены в WB ({stockImportPreview.skipped_unknown_details.length})
                  </summary>
                  <ul>
                    {stockImportPreview.skipped_unknown_details.map((item) => (
                      <li key={item.barcode}>
                        <code>{item.barcode}</code> — {item.add_quantity} шт.
                      </li>
                    ))}
                  </ul>
                </details>
              )}

              <table className="whub-table">
                <thead>
                  <tr>
                    <th>Баркод</th>
                    <th>Товар</th>
                    <th>+</th>
                    <th>CRM</th>
                    <th>WB</th>
                    <th>Действие</th>
                  </tr>
                </thead>
                <tbody>
                  {stockImportPreview.rows.map((row) => (
                    <tr key={row.barcode}>
                      <td><code>{row.barcode}</code></td>
                      <td>{row.title || '—'}</td>
                      <td>+{row.add_quantity}</td>
                      <td>{row.crm_before} → {row.crm_after}</td>
                      <td>{row.wb_before} → {row.wb_after}</td>
                      <td>{row.will_create ? 'новая ячейка' : `яч. ${row.cell_number}`}</td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <div className="whub-actions">
                <button
                  type="button"
                  className="btn btn--primary"
                  disabled={loading || stockImportPreview.rows.length === 0}
                  onClick={() => void handleStockImportApply()}
                >
                  Применить ({stockImportPreview.rows.length})
                </button>
              </div>
            </>
          )}

          {stockImportResult && (
            <div className={`whub-import-result panel${stockImportResult.ok ? ' whub-import-result--ok' : ' whub-import-result--error'}`}>
              <h3>{stockImportResult.ok ? 'Импорт завершён успешно' : 'Импорт завершён с ошибками'}</h3>
              <pre className="whub-import-result__text">{buildImportResultMessage(stockImportResult)}</pre>
              {stockImportResult.mismatches.length > 0 && (
                <table className="whub-table whub-import-result__table">
                  <thead>
                    <tr>
                      <th>Баркод</th>
                      <th>+из файла</th>
                      <th>CRM было → ожид.</th>
                      <th>CRM факт</th>
                      <th>WB было → ожид.</th>
                      <th>WB факт</th>
                      <th>Ошибка</th>
                    </tr>
                  </thead>
                  <tbody>
                    {stockImportResult.mismatches.map((row) => (
                      <tr key={row.barcode}>
                        <td><code>{row.barcode}</code></td>
                        <td>{row.add_quantity}</td>
                        <td>{row.crm_before} → {row.crm_expected}</td>
                        <td>{row.crm_actual}</td>
                        <td>{row.wb_before} → {row.wb_expected}</td>
                        <td>{row.wb_actual}</td>
                        <td>{row.error}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
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

      {tab === 'transfer' && !isOzon && (
        <section className="panel">
          <p className="whub-hint">
            Перенос остатков между FBS-складами WB. Суммарный остаток баркода в CRM не меняется.
          </p>
          <div className="whub-transfer-toolbar">
            <button
              type="button"
              className="btn btn--secondary"
              disabled={!sellerId || loading}
              onClick={() => void handleLoadStockOverview()}
            >
              Обновить остатки из WB
            </button>
            <button
              type="button"
              className="btn btn--primary"
              disabled={!sellerId || loading || !canDistributeEvenly || distributableProducts.length === 0}
              onClick={handleDistributeAll}
              title={!canDistributeEvenly ? 'Нужно минимум 2 включённых FBS-склада' : undefined}
            >
              Распределить все
            </button>
            <button
              type="button"
              className="btn btn--secondary"
              disabled={!sellerId || loading || !canDistributeEvenly || selectedDistributeIds.size === 0}
              onClick={handleDistributeSelected}
              title={!canDistributeEvenly ? 'Нужно минимум 2 включённых FBS-склада' : undefined}
            >
              Распределить выбранные ({selectedDistributeIds.size})
            </button>
          </div>
          {!canDistributeEvenly && stockOverview && (
            <p className="whub-hint whub-hint--warn">
              Для равномерного распределения включите минимум 2 FBS-склада у селлера.
            </p>
          )}

          {stockOverview && (
            <table className="whub-table whub-table--transfer">
              <thead>
                <tr>
                  <th className="whub-table__check">
                    <input
                      type="checkbox"
                      checked={allDistributableSelected}
                      disabled={!canDistributeEvenly || distributableProducts.length === 0}
                      onChange={(e) => toggleSelectAllDistributable(e.target.checked)}
                      aria-label="Выбрать все товары с остатком"
                    />
                  </th>
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
                    <td className="whub-table__check">
                      <input
                        type="checkbox"
                        checked={selectedDistributeIds.has(product.product_id)}
                        disabled={!canDistributeEvenly || product.wb_total <= 0}
                        onChange={(e) => toggleDistributeSelection(product.product_id, e.target.checked)}
                        aria-label={`Выбрать ${product.barcode}`}
                      />
                    </td>
                    <td>{product.cell_number}</td>
                    <td>
                      <div className="whub-product-cell">
                        <ProductPhotoThumb url={product.photo_url} alt={product.name} />
                        <span>{product.name || '—'}</span>
                      </div>
                    </td>
                    <td><code>{product.barcode}</code></td>
                    <td><strong>{product.wb_total}</strong></td>
                    {stockOverview.warehouses.map((wh) => {
                      const row = product.by_warehouse.find((x) => x.warehouse_id === wh.id)
                      return <td key={wh.id}>{row?.quantity ?? 0}</td>
                    })}
                    <td className="whub-transfer-actions">
                      <button
                        type="button"
                        className="btn btn--small btn--secondary"
                        disabled={!canDistributeEvenly || product.wb_total <= 0 || loading}
                        onClick={() => handleDistributeProduct(product)}
                        title={!canDistributeEvenly ? 'Нужно минимум 2 склада' : product.wb_total <= 0 ? 'Нулевой остаток' : undefined}
                      >
                        Поровну
                      </button>
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
