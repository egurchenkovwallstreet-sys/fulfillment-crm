import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { Link } from 'react-router-dom'
import {
  fetchFreeCells,
  fetchSellers,
  lookupInventoryBarcode,
  retryInventory,
  submitInventory,
  type Cell,
  type CellLabelData,
  type InventoryLookup,
  type InventoryResponse,
  type Seller,
} from '../api/warehouse'
import { fetchSellerWarehouses, syncSellerWarehouses, type SellerWarehouse } from '../api/sellers'
import { CellLabelPrompt } from '../components/CellLabelPrompt'
import { StockBalanceModal, type StockBalanceModalData } from '../components/StockBalanceModal'
import { useMarketplace } from '../context/MarketplaceContext'
import { printCellLabel } from '../utils/cellLabelPrint'
import { hintWrapProps, uiHint } from '../utils/uiHint'
import './InventoryPage.css'

export function InventoryPage() {
  const { marketplace } = useMarketplace()
  const isOzon = marketplace === 'ozon'
  const barcodeRef = useRef<HTMLInputElement>(null)
  const quantityRef = useRef<HTMLInputElement>(null)
  const [sellers, setSellers] = useState<Seller[]>([])
  const [warehouses, setWarehouses] = useState<SellerWarehouse[]>([])
  const [cells, setCells] = useState<Cell[]>([])
  const [sellerId, setSellerId] = useState<number | ''>('')
  const [warehouseIds, setWarehouseIds] = useState<number[]>([])
  const [sessionActive, setSessionActive] = useState(false)
  const [completedBarcodes, setCompletedBarcodes] = useState<Set<string>>(new Set())
  const [resultModal, setResultModal] = useState<StockBalanceModalData | null>(null)
  const [pendingRetry, setPendingRetry] = useState<{
    barcode: string
    crmQuantity: number
  } | null>(null)
  const [barcode, setBarcode] = useState('')
  const [quantityInput, setQuantityInput] = useState('')
  const [productName, setProductName] = useState('')
  const [cellMode, setCellMode] = useState<'auto' | 'manual'>('auto')
  const [cellId, setCellId] = useState<number | ''>('')
  const [lookup, setLookup] = useState<InventoryLookup | null>(null)
  const [labelPrompt, setLabelPrompt] = useState<CellLabelData | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [sessionCount, setSessionCount] = useState(0)

  const sellerName = sellers.find((s) => s.id === sellerId)?.company_name ?? ''

  const cellLabelData = useMemo((): CellLabelData | null => {
    if (!lookup || !barcode.trim()) return null
    if (lookup.exists && lookup.product) {
      return {
        product_id: lookup.product.id,
        seller_name: lookup.product.seller_name || sellerName,
        cell_number: lookup.product.cell_number,
        barcode: lookup.product.barcode,
      }
    }
    if (!lookup.exists && cellMode === 'manual' && cellId) {
      const cell = cells.find((item) => item.id === cellId)
      if (!cell) return null
      return {
        seller_name: sellerName,
        cell_number: cell.number,
        barcode: barcode.trim(),
      }
    }
    return null
  }, [lookup, barcode, cellMode, cellId, cells, sellerName])

  const focusBarcode = useCallback(() => {
    window.setTimeout(() => barcodeRef.current?.focus(), 30)
  }, [])

  const loadWarehouses = useCallback(async (id: number) => {
    try {
      const data = await fetchSellerWarehouses(id)
      setWarehouses(data)
    } catch {
      setWarehouses([])
    }
  }, [])

  useEffect(() => {
    fetchSellers()
      .then((data) => {
        setSellers(data)
        if (data.length === 1) {
          setSellerId(data[0].id)
          void loadWarehouses(data[0].id)
        }
      })
      .catch((err) => setError(err instanceof Error ? err.message : 'Ошибка загрузки'))
  }, [loadWarehouses])

  useEffect(() => {
    if (!sellerId || sessionActive) return
    void loadWarehouses(Number(sellerId))
    fetchFreeCells(Number(sellerId))
      .then(setCells)
      .catch(() => setCells([]))
  }, [sellerId, sessionActive, loadWarehouses])

  useEffect(() => {
    if (sessionActive) focusBarcode()
  }, [sessionActive, focusBarcode])

  function toggleWarehouse(id: number, checked: boolean) {
    setWarehouseIds((prev) => {
      if (checked) return prev.includes(id) ? prev : [...prev, id]
      return prev.filter((item) => item !== id)
    })
  }

  function resetBarcodeForm() {
    setBarcode('')
    setQuantityInput('')
    setProductName('')
    setLookup(null)
    setCellMode('auto')
    setCellId('')
    focusBarcode()
  }

  function startSession() {
    setError('')
    if (!sellerId) {
      setError('Выберите селлера')
      return
    }
    if (!isOzon && warehouseIds.length < 1) {
      setError('Выберите хотя бы один FBS-склад')
      return
    }
    setSessionActive(true)
    setSessionCount(0)
    setCompletedBarcodes(new Set())
    setResultModal(null)
    setPendingRetry(null)
    resetBarcodeForm()
  }

  function finishSession() {
    setSessionActive(false)
    setWarehouseIds([])
    setCompletedBarcodes(new Set())
    setResultModal(null)
    setPendingRetry(null)
    resetBarcodeForm()
    setError('')
  }

  function handlePrintCellLabel() {
    if (!cellLabelData) return
    printCellLabel(cellLabelData, true)
  }

  async function handleSyncWarehouses() {
    if (!sellerId) return
    setLoading(true)
    setError('')
    try {
      const result = await syncSellerWarehouses(Number(sellerId))
      setWarehouses(result.warehouses)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка загрузки складов WB')
    } finally {
      setLoading(false)
    }
  }

  async function handleLookup() {
    setError('')
    const trimmed = barcode.trim()
    if (!sellerId || !trimmed) {
      setError('Отсканируйте баркод')
      return
    }
    if (completedBarcodes.has(trimmed)) {
      setError(`Баркод ${trimmed} уже инвентаризирован в этой сессии — сканируйте следующий`)
      setLookup(null)
      focusBarcode()
      return
    }
    setLoading(true)
    try {
      const result = await lookupInventoryBarcode(Number(sellerId), trimmed)
      setLookup(result)
      if (result.exists && result.product) {
        setQuantityInput(String(result.product.quantity))
      } else {
        setCellMode('auto')
        setCellId('')
        setQuantityInput('')
      }
      window.setTimeout(() => quantityRef.current?.focus(), 50)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка поиска')
      setLookup(null)
      focusBarcode()
    } finally {
      setLoading(false)
    }
  }

  function handleBarcodeKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') {
      e.preventDefault()
      void handleLookup()
    }
  }

  function inventoryToModal(result: InventoryResponse): StockBalanceModalData {
    return {
      barcode: result.product.barcode,
      cellNumber: result.product.cell_number,
      verified: result.verified,
      restockRequired: result.restock_required,
      message: result.message,
      crmQuantityBefore: result.crm_quantity_before,
      crmQuantityAfter: result.crm_quantity_after,
      reservedNewOrders: result.reserved_new_orders,
      wbQuantityTarget: result.wb_target_quantity,
      wbQuantityActual: result.wb_total_actual,
      physicalQuantity: result.physical_quantity,
      warehouses: result.warehouses,
    }
  }

  async function handleResultConfirm() {
    if (!resultModal) return

    if (resultModal.verified) {
      setResultModal(null)
      setPendingRetry(null)
      resetBarcodeForm()
      return
    }

    if (!pendingRetry || !sellerId) {
      setResultModal(null)
      resetBarcodeForm()
      return
    }

    setLoading(true)
    setError('')
    try {
      const retried = await retryInventory({
        seller_id: Number(sellerId),
        barcode: pendingRetry.barcode,
        crm_quantity: pendingRetry.crmQuantity,
        warehouse_ids: warehouseIds,
      })
      if (retried.verified) {
        setResultModal(null)
        setPendingRetry(null)
        resetBarcodeForm()
      } else {
        setResultModal(inventoryToModal(retried))
        setPendingRetry({
          barcode: pendingRetry.barcode,
          crmQuantity: retried.crm_quantity_after,
        })
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка перезаписи остатков')
    } finally {
      setLoading(false)
    }
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError('')
    const trimmed = barcode.trim()
    if (!lookup) {
      setError('Сначала отсканируйте баркод (Enter)')
      return
    }
    if (completedBarcodes.has(trimmed)) {
      setError(`Баркод ${trimmed} уже инвентаризирован в этой сессии`)
      return
    }

    const quantity = parseInt(quantityInput, 10)
    if (!Number.isFinite(quantity) || quantity < 0) {
      setError('Укажите фактическое количество — целое число от 0')
      return
    }

    setLoading(true)
    try {
      const result = await submitInventory({
        seller_id: Number(sellerId),
        barcode: trimmed,
        quantity,
        warehouse_ids: isOzon ? [] : warehouseIds,
        cell_mode: lookup.exists ? 'auto' : cellMode,
        cell_id: !lookup.exists && cellMode === 'manual' ? Number(cellId) : null,
        name: productName,
      })
      setSessionCount((value) => value + 1)
      setCompletedBarcodes((prev) => new Set(prev).add(trimmed))
      setPendingRetry({
        barcode: trimmed,
        crmQuantity: result.crm_quantity_after,
      })
      setResultModal(inventoryToModal(result))
      if (result.print_cell_label && result.cell_label) {
        setLabelPrompt(result.cell_label)
      }
      setBarcode('')
      setQuantityInput('')
      setProductName('')
      setLookup(null)
      setCellMode('auto')
      setCellId('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка инвентаризации')
    } finally {
      setLoading(false)
    }
  }

  const selectedWarehouses = warehouses.filter((wh) => warehouseIds.includes(wh.id))

  return (
    <div className="page inventory-page">
      <header className="page__header inventory-page__header">
        <div>
          <h1>Инвентаризация</h1>
          <p>
            Скан баркода → факт на полке в CRM → в ЛК WB минус «Новые». Завершение — отдельной кнопкой.
          </p>
        </div>
        <Link to="/warehouse" className="btn btn--secondary inventory-btn" {...uiHint('Вернуться на главную страницу склада.')}>
          ← Склад
        </Link>
      </header>

      {error && <div className="alert alert--error">{error}</div>}

      {!sessionActive ? (
        <section className="panel inventory-setup">
          <h2>Начало инвентаризации</h2>
          <div className="inventory-setup__grid">
            <label className="inventory-field">
              Селлер
              <select
                className="inventory-control"
                value={sellerId}
                onChange={(e) => {
                  setSellerId(e.target.value ? Number(e.target.value) : '')
                  setWarehouseIds([])
                }}
              >
                <option value="">— выберите —</option>
                {sellers.map((s) => (
                  <option key={s.id} value={s.id}>{s.company_name}</option>
                ))}
              </select>
            </label>
            <div className="inventory-setup__warehouses">
              <div className="inventory-setup__warehouses-head">
                <strong>FBS-склады для остатков в WB</strong>
                <span {...hintWrapProps('Подтянуть список FBS-складов селлера из личного кабинета WB.')}>
                  <button
                    type="button"
                    className="btn btn--secondary inventory-btn inventory-btn--compact"
                    disabled={!sellerId || loading}
                    onClick={() => void handleSyncWarehouses()}
                  >
                    Загрузить из WB
                  </button>
                </span>
              </div>
              {warehouses.length === 0 ? (
                <p className="inventory-hint">Выберите селлера и загрузите склады</p>
              ) : (
                <ul className="inventory-warehouse-list">
                  {warehouses.map((wh) => (
                    <li key={wh.id}>
                      <label>
                        <input
                          type="checkbox"
                          checked={warehouseIds.includes(wh.id)}
                          onChange={(e) => toggleWarehouse(wh.id, e.target.checked)}
                        />
                        {wh.name || `Склад #${wh.wb_warehouse_id}`}
                      </label>
                    </li>
                  ))}
                </ul>
              )}
              {warehouseIds.length >= 2 && (
                <p className="inventory-hint">
                  Остаток будет распределён поровну между {warehouseIds.length} складами
                </p>
              )}
            </div>
          </div>
          <span {...hintWrapProps('Начать сессию пересчёта: выберите селлера и хотя бы один FBS-склад.')}>
            <button
              type="button"
              className="btn btn--danger inventory-btn inventory-btn--large"
              disabled={!sellerId || (!isOzon && warehouseIds.length < 1) || loading}
              onClick={startSession}
            >
              Начать инвентаризацию
            </button>
          </span>
        </section>
      ) : (
        <>
          <section className="panel inventory-session">
            <div className="inventory-session__meta">
              <div>
                <strong>{sellerName}</strong>
                <span className="inventory-session__warehouses">
                  {selectedWarehouses.map((wh) => wh.name || `#${wh.wb_warehouse_id}`).join(' · ')}
                </span>
              </div>
              <div className="inventory-session__actions">
                <span className="inventory-session__count">Сохранено: {sessionCount}</span>
                <button
                  type="button"
                  className="btn btn--danger inventory-btn"
                  onClick={finishSession}
                  {...uiHint('Завершить сессию инвентаризации.')}
                >
                  Закончить инвентаризацию
                </button>
              </div>
            </div>
          </section>

          <form className="panel inventory-form" onSubmit={(e) => void handleSubmit(e)}>
            <div className="inventory-scan">
              <label className="inventory-field inventory-field--barcode">
                Баркод
                <input
                  ref={barcodeRef}
                  className="inventory-control inventory-control--barcode"
                  type="text"
                  value={barcode}
                  onChange={(e) => setBarcode(e.target.value)}
                  onKeyDown={handleBarcodeKeyDown}
                  placeholder="Сканируйте следующий баркод"
                  autoComplete="off"
                  autoFocus
                  inputMode="numeric"
                />
              </label>
              <span {...hintWrapProps('Найти товар по баркоду в CRM перед вводом фактического количества.')}>
                <button
                  type="button"
                  className="btn btn--secondary inventory-btn inventory-btn--lookup"
                  disabled={loading || !barcode.trim()}
                  onClick={() => void handleLookup()}
                >
                  Найти товар
                </button>
              </span>
            </div>

            {lookup && (
              <div className="inventory-product">
                {lookup.exists && lookup.product ? (
                  <div className="inventory-product-card">
                    <div className="inventory-product-card__main">
                      <strong>{lookup.product.name || '—'}</strong>
                      <span className="inventory-product-card__meta">
                        В CRM сейчас: {lookup.product.quantity} шт.
                      </span>
                    </div>
                    <div className="inventory-cell-badge">
                      <span className="inventory-cell-badge__label">Ячейка</span>
                      <span className="inventory-cell-badge__number">№{lookup.product.cell_number}</span>
                    </div>
                  </div>
                ) : (
                  <>
                    <p className="inventory-hint">Новый баркод — будет создан товар и ячейка</p>
                    <label className="inventory-field">
                      Название (необязательно)
                      <input
                        className="inventory-control"
                        type="text"
                        value={productName}
                        onChange={(e) => setProductName(e.target.value)}
                        placeholder={lookup.marking?.title || ''}
                      />
                    </label>
                    <fieldset className="inventory-fieldset">
                      <legend>Ячейка</legend>
                      <label>
                        <input
                          type="radio"
                          checked={cellMode === 'auto'}
                          onChange={() => setCellMode('auto')}
                        />
                        Автоматически
                      </label>
                      <label>
                        <input
                          type="radio"
                          checked={cellMode === 'manual'}
                          onChange={() => setCellMode('manual')}
                        />
                        Вручную
                      </label>
                      {cellMode === 'manual' && (
                        <select
                          className="inventory-control"
                          value={cellId}
                          onChange={(e) => setCellId(e.target.value ? Number(e.target.value) : '')}
                        >
                          <option value="">— выберите —</option>
                          {cells.map((cell) => (
                            <option key={cell.id} value={cell.id}>
                              №{cell.number}{cell.is_occupied ? ' (занята)' : ''}
                            </option>
                          ))}
                        </select>
                      )}
                    </fieldset>
                  </>
                )}

                {cellLabelData && (
                  <button
                    type="button"
                    className="btn btn--secondary inventory-btn inventory-btn--print"
                    onClick={handlePrintCellLabel}
                  >
                    Распечатать этикетку ячейки
                  </button>
                )}

                <label className="inventory-field">
                  Факт на полке (включая товар под заказы «Новые»)
                  <input
                    ref={quantityRef}
                    className="inventory-control inventory-control--quantity"
                    type="number"
                    min={0}
                    step={1}
                    value={quantityInput}
                    onChange={(e) => setQuantityInput(e.target.value)}
                    required
                  />
                </label>

                <button
                  type="submit"
                  className="btn btn--danger inventory-btn inventory-btn--large"
                  disabled={loading}
                >
                  {loading ? 'Сохранение…' : 'Сохранить'}
                </button>
              </div>
            )}
          </form>
        </>
      )}

      {labelPrompt && (
        <CellLabelPrompt
          label={labelPrompt}
          onClose={() => {
            setLabelPrompt(null)
            focusBarcode()
          }}
        />
      )}

      {resultModal && (
        <StockBalanceModal
          data={resultModal}
          loading={loading}
          onConfirm={handleResultConfirm}
        />
      )}
    </div>
  )
}
