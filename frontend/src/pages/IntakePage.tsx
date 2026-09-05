import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import {
  applyWbSyncAuto,
  fetchFreeCells,
  fetchIntakeHistory,
  fetchSellers,
  lookupBarcode,
  previewWbSyncIntake,
  retryIntake,
  submitIntake,
  type Cell,
  type CellLabelData,
  type IntakeHistoryItem,
  type IntakeLookup,
  type IntakeResponse,
  type Seller,
  type StockMode,
  type SyncVariant,
  type WbSyncPreviewItem,
  type WbSyncPreviewResult,
} from '../api/warehouse'
import { fetchSellerWarehouses, syncSellerWarehouses, type SellerWarehouse } from '../api/sellers'
import { CellLabelPrompt } from '../components/CellLabelPrompt'
import { StockBalanceModal, type StockBalanceModalData } from '../components/StockBalanceModal'
import { printCellLabels } from '../utils/cellLabelPrint'
import { useMarketplace } from '../context/MarketplaceContext'
import { hintWrapProps, uiHint } from '../utils/uiHint'
import './IntakePage.css'

export function IntakePage() {
  const { marketplace } = useMarketplace()
  const isOzon = marketplace === 'ozon'
  const barcodeRef = useRef<HTMLInputElement>(null)
  const [sellers, setSellers] = useState<Seller[]>([])
  const [cells, setCells] = useState<Cell[]>([])
  const [history, setHistory] = useState<IntakeHistoryItem[]>([])
  const [warehouses, setWarehouses] = useState<SellerWarehouse[]>([])
  const [sellerId, setSellerId] = useState<number | ''>('')
  const [warehouseId, setWarehouseId] = useState<number | ''>('')
  const [stockMode, setStockMode] = useState<StockMode>('intake')
  const [syncVariant, setSyncVariant] = useState<SyncVariant>('auto')
  const [verifiedStockMatch, setVerifiedStockMatch] = useState(false)
  const [wbSyncPreview, setWbSyncPreview] = useState<WbSyncPreviewResult | null>(null)
  const [selectedBarcodes, setSelectedBarcodes] = useState<Set<string>>(new Set())
  const [wbSyncLabels, setWbSyncLabels] = useState<CellLabelData[]>([])
  const [barcode, setBarcode] = useState('')
  const [quantityInput, setQuantityInput] = useState('1')
  const [productName, setProductName] = useState('')
  const [lengthCm, setLengthCm] = useState('')
  const [widthCm, setWidthCm] = useState('')
  const [heightCm, setHeightCm] = useState('')
  const [cellMode, setCellMode] = useState<'auto' | 'manual'>('auto')
  const [cellId, setCellId] = useState<number | ''>('')
  const [lookup, setLookup] = useState<IntakeLookup | null>(null)
  const [labelPrompt, setLabelPrompt] = useState<CellLabelData | null>(null)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [loading, setLoading] = useState(false)
  const [resultModal, setResultModal] = useState<StockBalanceModalData | null>(null)
  const [pendingRetry, setPendingRetry] = useState<{
    barcode: string
    crmQuantity: number
    stockMode: 'intake' | 'set_actual'
  } | null>(null)

  const loadWarehouses = useCallback(async (id: number) => {
    try {
      const data = await fetchSellerWarehouses(id)
      setWarehouses(data)
      if (data.length === 1) {
        setWarehouseId(data[0].id)
      }
    } catch {
      setWarehouses([])
    }
  }, [])

  const loadInitial = useCallback(async () => {
    try {
      const [sellersData, historyData] = await Promise.all([
        fetchSellers(),
        fetchIntakeHistory(),
      ])
      setSellers(sellersData)
      setHistory(historyData)
      if (sellersData.length === 1) {
        setSellerId(sellersData[0].id)
        await loadWarehouses(sellersData[0].id)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка загрузки')
    }
  }, [loadWarehouses])

  useEffect(() => {
    loadInitial()
    barcodeRef.current?.focus()
  }, [loadInitial])

  useEffect(() => {
    if (!sellerId) {
      setWarehouses([])
      setWarehouseId('')
      setCells([])
      return
    }
    loadWarehouses(Number(sellerId))
    fetchFreeCells(Number(sellerId))
      .then(setCells)
      .catch(() => setCells([]))
  }, [sellerId, loadWarehouses])

  async function handleSyncWarehouses() {
    if (!sellerId) return
    setLoading(true)
    setError('')
    try {
      const result = await syncSellerWarehouses(Number(sellerId))
      setWarehouses(result.warehouses)
      setSuccess(`Склады WB обновлены: ${result.total} шт.`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка загрузки складов WB')
    } finally {
      setLoading(false)
    }
  }

  async function handleLookup() {
    setError('')
    setSuccess('')
    setVerifiedStockMatch(false)
    if (!sellerId || !barcode.trim() || (!isOzon && !warehouseId)) {
      setError(isOzon ? 'Выберите селлера и отсканируйте баркод' : 'Выберите селлера, склад FBS и отсканируйте баркод')
      return
    }
    setLoading(true)
    try {
      const result = await lookupBarcode(
        Number(sellerId),
        barcode.trim(),
        isOzon ? undefined : Number(warehouseId),
      )
      setLookup(result)
      if (result.exists && result.product) {
        setLengthCm(result.product.length_cm ?? '')
        setWidthCm(result.product.width_cm ?? '')
        setHeightCm(result.product.height_cm ?? '')
      } else {
        setLengthCm('')
        setWidthCm('')
        setHeightCm('')
      }
      if (!result.exists) {
        setCellMode('auto')
        setCellId('')
      }
      if (stockMode === 'sync_from_wb' && result.wb_stock != null) {
        setQuantityInput(String(result.wb_stock))
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка поиска')
      setLookup(null)
    } finally {
      setLoading(false)
    }
  }

  function handleBarcodeKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') {
      e.preventDefault()
      handleLookup()
    }
  }

  function intakeToModal(result: IntakeResponse): StockBalanceModalData | null {
    if (result.verified == null || result.crm_quantity_after == null) return null
    return {
      barcode: result.product.barcode,
      cellNumber: result.product.cell_number,
      verified: result.verified,
      restockRequired: Boolean(result.restock_required),
      message: result.balance_message || result.message,
      crmQuantityBefore: result.crm_quantity_before ?? 0,
      crmQuantityAfter: result.crm_quantity_after,
      reservedNewOrders: result.reserved_new_orders ?? 0,
      wbQuantityBefore: result.wb_quantity_before,
      wbQuantityTarget: result.wb_quantity_target ?? 0,
      wbQuantityActual: result.wb_quantity_actual,
      intakeQuantity: result.intake_quantity,
      physicalQuantity: result.physical_quantity ?? undefined,
      warehouseName: result.warehouse_name,
    }
  }

  function resetAfterIntake() {
    setBarcode('')
    setLookup(null)
    setQuantityInput('1')
    setProductName('')
    setCellId('')
    setVerifiedStockMatch(false)
    barcodeRef.current?.focus()
  }

  async function handleResultConfirm() {
    if (!resultModal) return

    if (resultModal.verified) {
      setResultModal(null)
      setPendingRetry(null)
      resetAfterIntake()
      if (sellerId) {
        const [cellsData, historyData] = await Promise.all([
          fetchFreeCells(Number(sellerId)),
          fetchIntakeHistory(),
        ])
        setCells(cellsData)
        setHistory(historyData)
      }
      return
    }

    if (!pendingRetry || !sellerId || !warehouseId) {
      setResultModal(null)
      resetAfterIntake()
      return
    }

    setLoading(true)
    setError('')
    try {
      const retried = await retryIntake({
        seller_id: Number(sellerId),
        barcode: pendingRetry.barcode,
        crm_quantity: pendingRetry.crmQuantity,
        wb_warehouse_id: Number(warehouseId),
        stock_mode: pendingRetry.stockMode,
      })
      const modal = intakeToModal(retried)
      if (!modal) {
        setResultModal(null)
        setPendingRetry(null)
        resetAfterIntake()
        return
      }
      if (retried.verified) {
        setResultModal(null)
        setPendingRetry(null)
        resetAfterIntake()
        const [cellsData, historyData] = await Promise.all([
          fetchFreeCells(Number(sellerId)),
          fetchIntakeHistory(),
        ])
        setCells(cellsData)
        setHistory(historyData)
      } else {
        setResultModal(modal)
        setPendingRetry({
          barcode: pendingRetry.barcode,
          crmQuantity: retried.crm_quantity_after ?? pendingRetry.crmQuantity,
          stockMode: pendingRetry.stockMode,
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
    setSuccess('')

    if (!sellerId || !barcode.trim() || (!isOzon && !warehouseId)) {
      setError(isOzon ? 'Укажите селлера и баркод' : 'Укажите селлера, склад FBS и баркод')
      return
    }
    if (!lookup) {
      setError('Сначала отсканируйте баркод (Enter)')
      return
    }
    if (stockMode === 'sync_from_wb' && syncVariant !== 'scan' && !verifiedStockMatch) {
      setError('Подтвердите сверку остатков на фулфилменте')
      return
    }

    const quantity = stockMode === 'sync_from_wb'
      ? (lookup.wb_stock ?? 0)
      : parseInt(quantityInput, 10)

    if (stockMode === 'intake' && (!Number.isFinite(quantity) || quantity < 1)) {
      setError('Укажите количество — целое число от 1')
      return
    }
    if (stockMode === 'set_actual' && (!Number.isFinite(quantity) || quantity < 0)) {
      setError('Укажите фактический остаток — целое число от 0')
      return
    }

    setLoading(true)
    try {
      const dimension = (value: string) => {
        const trimmed = value.replace(',', '.').trim()
        return trimmed ? trimmed : undefined
      }
      const result = await submitIntake({
        seller_id: Number(sellerId),
        wb_warehouse_id: isOzon ? undefined : Number(warehouseId),
        barcode: barcode.trim(),
        quantity,
        stock_mode: isOzon ? 'intake' : stockMode,
        sync_variant: isOzon ? undefined : (stockMode === 'sync_from_wb' ? syncVariant : undefined),
        verified_stock_match: stockMode === 'sync_from_wb' && syncVariant !== 'scan'
          ? verifiedStockMatch
          : false,
        cell_mode: lookup.exists || isSyncScan ? 'auto' : cellMode,
        cell_id: !lookup.exists && cellMode === 'manual' ? Number(cellId) : null,
        name: productName,
        length_cm: dimension(lengthCm),
        width_cm: dimension(widthCm),
        height_cm: dimension(heightCm),
      })

      const showBalanceModal = !isOzon && (stockMode === 'intake' || stockMode === 'set_actual')
      const modal = showBalanceModal ? intakeToModal(result) : null

      if (modal) {
        setPendingRetry({
          barcode: barcode.trim(),
          crmQuantity: result.crm_quantity_after ?? result.product.quantity,
          stockMode: stockMode as 'intake' | 'set_actual',
        })
        setResultModal(modal)
        if (result.print_cell_label && result.cell_label) {
          setLabelPrompt(result.cell_label)
        }
        setBarcode('')
        setLookup(null)
        setQuantityInput('1')
        setProductName('')
        setLengthCm('')
        setWidthCm('')
        setHeightCm('')
        setCellId('')
        setVerifiedStockMatch(false)
      } else {
        setSuccess(
          `${result.message} Ячейка №${result.product.cell_number}, остаток CRM: ${result.product.quantity} шт.${
            result.product.requires_marking ? ' · Товар с Честным знаком' : ''
          }`,
        )
        if (result.print_cell_label && result.cell_label) {
          setLabelPrompt(result.cell_label)
        }
        resetAfterIntake()
        const [cellsData, historyData] = await Promise.all([
          fetchFreeCells(Number(sellerId)),
          fetchIntakeHistory(),
        ])
        setCells(cellsData)
        setHistory(historyData)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка приёмки')
    } finally {
      setLoading(false)
    }
  }

  function resetWbSyncState() {
    setWbSyncPreview(null)
    setSelectedBarcodes(new Set())
    setWbSyncLabels([])
  }

  function resetForm() {
    setBarcode('')
    setLookup(null)
    setVerifiedStockMatch(false)
    setError('')
    setSuccess('')
    barcodeRef.current?.focus()
  }

  function handleStockModeChange(mode: StockMode) {
    setStockMode(mode)
    setVerifiedStockMatch(false)
    setLookup(null)
    resetWbSyncState()
    if (mode === 'sync_from_wb') {
      setSyncVariant('auto')
    }
  }

  function handleSyncVariantChange(variant: SyncVariant) {
    setSyncVariant(variant)
    setLookup(null)
    resetWbSyncState()
  }

  function toggleBarcodeSelection(barcode: string, checked: boolean) {
    setSelectedBarcodes((prev) => {
      const next = new Set(prev)
      if (checked) next.add(barcode)
      else next.delete(barcode)
      return next
    })
  }

  function toggleSelectAll(checked: boolean) {
    if (!wbSyncPreview) return
    if (checked) {
      setSelectedBarcodes(new Set(wbSyncPreview.items.map((item) => item.barcode)))
    } else {
      setSelectedBarcodes(new Set())
    }
  }

  async function handleLoadWbSyncPreview() {
    if (!sellerId || !warehouseId) {
      setError('Выберите селлера и склад FBS')
      return
    }
    setLoading(true)
    setError('')
    setSuccess('')
    try {
      const result = await previewWbSyncIntake(Number(sellerId), Number(warehouseId))
      setWbSyncPreview(result)
      setSelectedBarcodes(new Set(result.items.map((item) => item.barcode)))
      setWbSyncLabels([])
      setSuccess(`Загружено ${result.items.length} позиций с остатком WB (${result.warehouse_name})`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось загрузить остатки WB')
      setWbSyncPreview(null)
      setSelectedBarcodes(new Set())
    } finally {
      setLoading(false)
    }
  }

  async function handleApplyWbSyncAuto() {
    if (!sellerId || !warehouseId || !wbSyncPreview) return
    const barcodes = Array.from(selectedBarcodes)
    if (barcodes.length < 1) {
      setError('Отметьте хотя бы один баркод')
      return
    }
    setLoading(true)
    setError('')
    setSuccess('')
    try {
      const result = await applyWbSyncAuto(Number(sellerId), Number(warehouseId), barcodes)
      setWbSyncLabels(result.cell_labels)
      setSuccess(result.message)
      const [cellsData, historyData] = await Promise.all([
        fetchFreeCells(Number(sellerId)),
        fetchIntakeHistory(),
      ])
      setCells(cellsData)
      setHistory(historyData)
      await handleLoadWbSyncPreview()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка автоматической сверки')
    } finally {
      setLoading(false)
    }
  }

  function handlePrintWbSyncLabels(all: boolean) {
    const labels = all
      ? wbSyncLabels
      : wbSyncLabels.filter((label) => selectedBarcodes.has(label.barcode))
    if (labels.length < 1) {
      setError(all ? 'Нет новых этикеток для печати' : 'Выберите позиции с новыми ячейками')
      return
    }
    printCellLabels(labels, true)
    setSuccess(`Отправлено на печать: ${labels.length} этикеток`)
  }

  function renderWbSyncRow(item: WbSyncPreviewItem) {
    const checked = selectedBarcodes.has(item.barcode)
    return (
      <tr key={item.barcode}>
        <td>
          <input
            type="checkbox"
            checked={checked}
            onChange={(e) => toggleBarcodeSelection(item.barcode, e.target.checked)}
          />
        </td>
        <td><code>{item.barcode}</code></td>
        <td>{item.tech_size || '—'}</td>
        <td><strong>{item.wb_stock}</strong></td>
        <td>{item.already_in_crm ? (item.crm_quantity ?? '—') : '—'}</td>
        <td><strong>{item.cell_number || '—'}</strong></td>
        <td>{item.already_in_crm ? 'В CRM' : 'Новый'}</td>
      </tr>
    )
  }

  const isSyncMode = stockMode === 'sync_from_wb'
  const isSetActualMode = stockMode === 'set_actual'
  const isSyncAuto = isSyncMode && syncVariant === 'auto'
  const isSyncScan = isSyncMode && syncVariant === 'scan'
  const enabledWarehouses = warehouses
  const allSelected =
    wbSyncPreview != null &&
    wbSyncPreview.items.length > 0 &&
    wbSyncPreview.items.every((item) => selectedBarcodes.has(item.barcode))

  return (
    <>
      <header className="topbar">
        <div>
          <h1>Приёмка товара</h1>
          <p>Селлер → склад FBS → баркод → количество → остатки в CRM и ЛК WB</p>
        </div>
      </header>

      <div className="intake-grid">
        <section className="panel intake-form-panel">
          <form onSubmit={handleSubmit}>
            <label className="intake-field">
              Селлер
              <select
                value={sellerId}
                onChange={(e) => {
                  setSellerId(e.target.value ? Number(e.target.value) : '')
                  setWarehouseId('')
                  setLookup(null)
                }}
                required
              >
                <option value="">— выберите —</option>
                {sellers.map((s) => (
                  <option key={s.id} value={s.id}>{s.company_name}</option>
                ))}
              </select>
            </label>

            {!isOzon && (
            <div className="intake-warehouses">
              <div className="intake-warehouses__head">
                <span className="intake-field__label">Склад FBS (точка отгрузки WB)</span>
                <span {...hintWrapProps('Подтянуть список FBS-складов селлера из личного кабинета WB.')}>
                  <button
                    type="button"
                    className="btn btn--secondary btn--small"
                    onClick={handleSyncWarehouses}
                    disabled={loading || !sellerId}
                  >
                    Загрузить из WB
                  </button>
                </span>
              </div>
              {sellerId && enabledWarehouses.length === 0 && (
                <p className="intake-hint">Нажмите «Загрузить из WB», чтобы получить склады</p>
              )}
              <select
                value={warehouseId}
                onChange={(e) => {
                  setWarehouseId(e.target.value ? Number(e.target.value) : '')
                  setLookup(null)
                  resetWbSyncState()
                }}
                required
                disabled={!sellerId}
              >
                <option value="">— выберите склад —</option>
                {enabledWarehouses.map((wh) => (
                  <option key={wh.id} value={wh.id}>
                    {wh.name || `Склад #${wh.wb_warehouse_id}`}
                  </option>
                ))}
              </select>
            </div>
            )}

            {!isOzon && (
            <fieldset className="intake-stock-mode">
              <legend>Остатки</legend>
              <label>
                <input
                  type="radio"
                  name="stockMode"
                  checked={stockMode === 'intake'}
                  onChange={() => handleStockModeChange('intake')}
                />
                <strong>Приёмка</strong> — CRM: было + принято; ЛК WB: CRM − «Новые»
              </label>
              <label>
                <input
                  type="radio"
                  name="stockMode"
                  checked={stockMode === 'sync_from_wb'}
                  onChange={() => handleStockModeChange('sync_from_wb')}
                />
                <strong>Сверка с WB</strong> — установить остаток CRM по ЛК WB
              </label>
              <label>
                <input
                  type="radio"
                  name="stockMode"
                  checked={stockMode === 'set_actual'}
                  onChange={() => handleStockModeChange('set_actual')}
                />
                <strong>Факт на полке</strong> — CRM = пересчёт; ЛК WB = CRM − «Новые»
              </label>
            </fieldset>
            )}

            {isSyncMode && (
            <fieldset className="intake-sync-variant">
              <legend>Режим сверки</legend>
              <label>
                <input
                  type="radio"
                  name="syncVariant"
                  checked={syncVariant === 'auto'}
                  onChange={() => handleSyncVariantChange('auto')}
                />
                <strong>Автоматически</strong> — все остатки WB, ячейки и CRM
              </label>
              <label>
                <input
                  type="radio"
                  name="syncVariant"
                  checked={syncVariant === 'scan'}
                  onChange={() => handleSyncVariantChange('scan')}
                />
                <strong>По сканированию</strong> — баркод → ячейка → печать
              </label>
            </fieldset>
            )}

            {isSyncAuto && (
            <div className="intake-wb-sync-auto">
              <span {...hintWrapProps('Загрузить все остатки с выбранного FBS-склада WB для автоматической сверки.')}>
                <button
                  type="button"
                  className="btn btn--secondary"
                  onClick={() => void handleLoadWbSyncPreview()}
                  disabled={loading || !sellerId || !warehouseId}
                >
                  {loading ? 'Загрузка…' : 'Загрузить остатки из WB'}
                </button>
              </span>
              {wbSyncPreview && (
                <>
                  <p className="intake-hint">
                    Склад «{wbSyncPreview.warehouse_name}»: {wbSyncPreview.items.length} позиций с остатком WB
                  </p>
                  <div className="intake-wb-sync-table-wrap">
                    <table className="intake-wb-sync-table">
                      <thead>
                        <tr>
                          <th>
                            <input
                              type="checkbox"
                              checked={allSelected}
                              onChange={(e) => toggleSelectAll(e.target.checked)}
                              aria-label="Выбрать все"
                            />
                          </th>
                          <th>Баркод</th>
                          <th>Размер</th>
                          <th>WB</th>
                          <th>CRM</th>
                          <th>Ячейка</th>
                          <th>Статус</th>
                        </tr>
                      </thead>
                      <tbody>
                        {wbSyncPreview.items.map(renderWbSyncRow)}
                      </tbody>
                    </table>
                  </div>
                  <div className="intake-actions">
                    <span {...hintWrapProps('Применить сверку к отмеченным баркодам: остатки CRM и ячейки по WB.')}>
                      <button
                        type="button"
                        className="btn btn--primary"
                        onClick={() => void handleApplyWbSyncAuto()}
                        disabled={loading || selectedBarcodes.size < 1}
                      >
                        Применить сверку ({selectedBarcodes.size})
                      </button>
                    </span>
                    <span {...hintWrapProps('Напечатать этикетки ячеек только для отмеченных позиций.')}>
                      <button
                        type="button"
                        className="btn btn--secondary"
                        onClick={() => handlePrintWbSyncLabels(false)}
                        disabled={wbSyncLabels.length < 1}
                      >
                        Печать выбранных этикеток
                      </button>
                    </span>
                    <span {...hintWrapProps('Напечатать этикетки ячеек для всех новых позиций после сверки.')}>
                      <button
                        type="button"
                        className="btn btn--secondary"
                        onClick={() => handlePrintWbSyncLabels(true)}
                        disabled={wbSyncLabels.length < 1}
                      >
                        Печать всех этикеток
                      </button>
                    </span>
                  </div>
                </>
              )}
            </div>
            )}

            {!isSyncAuto && (
            <>
            {isSyncScan && (
              <span {...hintWrapProps('Загрузить остатки WB для режима сверки по сканированию баркодов.')}>
                <button
                  type="button"
                  className="btn btn--secondary"
                  onClick={() => void handleLoadWbSyncPreview()}
                  disabled={loading || !sellerId || !warehouseId}
                >
                  {wbSyncPreview
                    ? `Остатки WB загружены (${wbSyncPreview.items.length})`
                    : 'Загрузить остатки из WB'}
                </button>
              </span>
            )}

            <label className="intake-field">
              Баркод (сканер)
              <input
                ref={barcodeRef}
                type="text"
                value={barcode}
                onChange={(e) => setBarcode(e.target.value)}
                onKeyDown={handleBarcodeKeyDown}
                placeholder="Наведите сканер и отсканируйте"
                autoComplete="off"
                disabled={!sellerId || (!isOzon && !warehouseId)}
              />
            </label>

            <span {...hintWrapProps('Найти товар по баркоду в CRM и подтянуть остаток WB.')}>
              <button
                type="button"
                className="btn btn--secondary"
                onClick={handleLookup}
                disabled={loading || !sellerId || (!isOzon && !warehouseId)}
              >
                {loading ? 'Поиск…' : 'Найти товар (Enter)'}
              </button>
            </span>

            {lookup?.exists && lookup.product && (
              <div className="intake-info intake-info--exists">
                <h3>Товар найден</h3>
                <p><strong>Ячейка:</strong> №{lookup.product.cell_number}</p>
                <p><strong>Остаток CRM:</strong> {lookup.product.quantity} шт.</p>
                {lookup.wb_stock != null && (
                  <p><strong>Остаток WB ({lookup.warehouse_name}):</strong> {lookup.wb_stock} шт.</p>
                )}
                {lookup.product.name && <p><strong>Название:</strong> {lookup.product.name}</p>}
                {lookup.product.requires_marking && (
                  <p className="intake-marking intake-marking--required">
                    Требует маркировку «Честный знак»
                  </p>
                )}
              </div>
            )}

            {lookup && !lookup.exists && isSyncScan && (
              <div className="intake-info intake-info--new">
                <h3>Новый баркод</h3>
                <p>Будет создан товар, ячейка назначится автоматически по возрастанию, этикетка — после сохранения.</p>
                {lookup.wb_stock != null && (
                  <p><strong>Остаток WB ({lookup.warehouse_name}):</strong> {lookup.wb_stock} шт.</p>
                )}
              </div>
            )}

            {lookup && !lookup.exists && !isSyncScan && (
              <div className="intake-info intake-info--new">
                <h3>Новый баркод</h3>
                <p>Товар не найден — будет создан и привязан к ячейке</p>
                {lookup.wb_stock != null && (
                  <p><strong>Остаток WB ({lookup.warehouse_name}):</strong> {lookup.wb_stock} шт.</p>
                )}
                {lookup.marking?.requires_marking && (
                  <p className="intake-marking intake-marking--required">
                    WB: товар подлежит обязательной маркировке «Честный знак»
                  </p>
                )}
                <label className="intake-field">
                  Название (необязательно)
                  <input
                    type="text"
                    value={productName}
                    onChange={(e) => setProductName(e.target.value)}
                    placeholder="Описание товара"
                  />
                </label>
                <fieldset className="intake-cell-mode">
                  <legend>Назначение ячейки</legend>
                  <label>
                    <input
                      type="radio"
                      name="cellMode"
                      checked={cellMode === 'auto'}
                      onChange={() => setCellMode('auto')}
                    />
                    Автоматически
                  </label>
                  <label>
                    <input
                      type="radio"
                      name="cellMode"
                      checked={cellMode === 'manual'}
                      onChange={() => setCellMode('manual')}
                    />
                    Вручную
                  </label>
                </fieldset>
                {cellMode === 'manual' && (
                  <label className="intake-field">
                    Ячейка
                    <select
                      value={cellId}
                      onChange={(e) => setCellId(e.target.value ? Number(e.target.value) : '')}
                      required
                    >
                      <option value="">— выберите ячейку —</option>
                      {cells.map((c) => (
                        <option key={c.id} value={c.id}>
                          №{c.number}{c.is_occupied ? ' (занята)' : ' (свободна)'}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
              </div>
            )}

            {lookup && isSetActualMode && (
              <div className="intake-info intake-info--new">
                <p>
                  CRM получит введённый факт на полке; в ЛК WB — этот факт минус заказы «Новые»
                  {lookup.product ? ` (сейчас в CRM: ${lookup.product.quantity} шт.)` : ''}.
                </p>
              </div>
            )}

            {lookup && isSyncMode && !isSyncScan && (
              <div className="intake-warning intake-warning--danger">
                <p>
                  <strong>Внимание!</strong> Остаток в CRM будет установлен равным остатку в ЛК WB
                  {lookup.wb_stock != null ? ` (${lookup.wb_stock} шт.)` : ''} на складе «{lookup.warehouse_name}».
                </p>
                <p>Перед подтверждением пересчитайте товар на фулфилменте и убедитесь, что факт совпадает с WB.</p>
                <label className="intake-warning__confirm">
                  <input
                    type="checkbox"
                    checked={verifiedStockMatch}
                    onChange={(e) => setVerifiedStockMatch(e.target.checked)}
                  />
                  Подтверждаю: на фулфилменте пересчитал, остатки совпадают с ЛК WB
                </label>
              </div>
            )}

            {lookup && (
              <>
                {!isSyncMode && (
                  <label className="intake-field intake-field--quantity">
                    {isSetActualMode ? 'Фактический остаток на полке' : 'Количество (факт при приёмке)'}
                    <input
                      type="text"
                      inputMode="numeric"
                      pattern="[0-9]*"
                      value={quantityInput}
                      onChange={(e) => setQuantityInput(e.target.value.replace(/\D/g, ''))}
                      placeholder={isSetActualMode ? '0' : '1'}
                      required
                    />
                  </label>
                )}

                {!isSyncMode && (
                  <fieldset className="intake-dimensions">
                    <legend>Габариты упаковки, см (для тарификации по литражу)</legend>
                    <p className="intake-hint">Проверьте и при необходимости измените — объём считается один раз на баркод.</p>
                    <div className="intake-dimensions__grid">
                      <label className="intake-field">
                        Длина
                        <input
                          type="text"
                          inputMode="decimal"
                          value={lengthCm}
                          onChange={(e) => setLengthCm(e.target.value)}
                          placeholder="см"
                        />
                      </label>
                      <label className="intake-field">
                        Ширина
                        <input
                          type="text"
                          inputMode="decimal"
                          value={widthCm}
                          onChange={(e) => setWidthCm(e.target.value)}
                          placeholder="см"
                        />
                      </label>
                      <label className="intake-field">
                        Высота
                        <input
                          type="text"
                          inputMode="decimal"
                          value={heightCm}
                          onChange={(e) => setHeightCm(e.target.value)}
                          placeholder="см"
                        />
                      </label>
                    </div>
                    {lookup.product?.volume_liters && (
                      <p className="intake-hint">Текущий объём: {lookup.product.volume_liters} л</p>
                    )}
                  </fieldset>
                )}

                {isSyncMode && lookup.wb_stock != null && (
                  <p className="intake-sync-qty">
                    Будет установлено в CRM: <strong>{lookup.wb_stock} шт.</strong> (из ЛК WB)
                  </p>
                )}

                <div className="intake-actions">
                  <span
                    {...hintWrapProps(
                      isSyncScan
                        ? 'Сверить остаток, назначить ячейку и отправить этикетку на печать.'
                        : isSyncMode
                          ? 'Установить остаток CRM по данным WB после подтверждения сверки.'
                          : isSetActualMode
                            ? 'Установить фактический остаток в CRM и ЛК WB.'
                            : 'Принять товар на склад CRM и обновить остатки в маркетплейсе.',
                    )}
                  >
                    <button
                      type="submit"
                      className="btn btn--primary"
                      disabled={loading || (isSyncMode && !isSyncScan && !verifiedStockMatch)}
                    >
                      {loading
                        ? 'Сохранение…'
                        : isSyncScan
                          ? 'Сверить, назначить ячейку и печать'
                          : isSyncMode
                            ? 'Установить остаток из WB'
                            : isSetActualMode
                              ? 'Установить фактический остаток'
                              : 'Принять на склад'}
                    </button>
                  </span>
                  <button type="button" className="btn btn--secondary" onClick={resetForm} {...uiHint('Очистить форму и вернуться к сканированию баркода.')}>
                    Сбросить
                  </button>
                </div>
              </>
            )}

            </>
            )}

            {error && <p className="intake-message intake-message--error">{error}</p>}
            {success && <p className="intake-message intake-message--success">{success}</p>}
          </form>
        </section>

        <section className="panel">
          <h2 className="section-title">Последние приёмки</h2>
          {history.length === 0 ? (
            <p className="intake-empty">Пока нет операций</p>
          ) : (
            <ul className="intake-history">
              {history.map((item) => (
                <li key={item.id}>
                  <strong>+{item.quantity} шт.</strong>
                  <span>{item.barcode}</span>
                  <span>№{item.cell_number} · {item.seller_name}</span>
                  <time>{new Date(item.created_at).toLocaleString('ru-RU')}</time>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      {labelPrompt && (
        <CellLabelPrompt label={labelPrompt} onClose={() => setLabelPrompt(null)} />
      )}

      {resultModal && (
        <StockBalanceModal
          data={resultModal}
          loading={loading}
          onConfirm={() => void handleResultConfirm()}
        />
      )}
    </>
  )
}
