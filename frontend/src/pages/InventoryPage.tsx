import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { Link } from 'react-router-dom'
import {
  fetchFreeCells,
  fetchSellers,
  lookupInventoryBarcode,
  submitInventory,
  type Cell,
  type CellLabelData,
  type InventoryLookup,
  type InventoryResponse,
  type Seller,
} from '../api/warehouse'
import { fetchSellerWarehouses, syncSellerWarehouses, type SellerWarehouse } from '../api/sellers'
import { CellLabelPrompt } from '../components/CellLabelPrompt'
import { printCellLabel } from '../utils/cellLabelPrint'
import './InventoryPage.css'

type VerifyModal = {
  kind: 'ok' | 'error'
  result: InventoryResponse
}

export function InventoryPage() {
  const barcodeRef = useRef<HTMLInputElement>(null)
  const quantityRef = useRef<HTMLInputElement>(null)
  const [sellers, setSellers] = useState<Seller[]>([])
  const [warehouses, setWarehouses] = useState<SellerWarehouse[]>([])
  const [cells, setCells] = useState<Cell[]>([])
  const [sellerId, setSellerId] = useState<number | ''>('')
  const [warehouseIds, setWarehouseIds] = useState<number[]>([])
  const [sessionActive, setSessionActive] = useState(false)
  const [barcode, setBarcode] = useState('')
  const [quantityInput, setQuantityInput] = useState('')
  const [productName, setProductName] = useState('')
  const [cellMode, setCellMode] = useState<'auto' | 'manual'>('auto')
  const [cellId, setCellId] = useState<number | ''>('')
  const [lookup, setLookup] = useState<InventoryLookup | null>(null)
  const [labelPrompt, setLabelPrompt] = useState<CellLabelData | null>(null)
  const [verifyModal, setVerifyModal] = useState<VerifyModal | null>(null)
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
    if (warehouseIds.length < 1) {
      setError('Выберите хотя бы один FBS-склад')
      return
    }
    setSessionActive(true)
    setSessionCount(0)
    resetBarcodeForm()
  }

  function finishSession() {
    setSessionActive(false)
    setWarehouseIds([])
    setVerifyModal(null)
    resetBarcodeForm()
    setError('')
  }

  function handlePrintCellLabel() {
    if (!cellLabelData) return
    printCellLabel(cellLabelData, true)
  }

  function closeVerifyModal() {
    setVerifyModal(null)
    focusBarcode()
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
    if (!sellerId || !barcode.trim()) {
      setError('Отсканируйте баркод')
      return
    }
    setLoading(true)
    try {
      const result = await lookupInventoryBarcode(Number(sellerId), barcode.trim())
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

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError('')
    if (!lookup) {
      setError('Сначала отсканируйте баркод (Enter)')
      return
    }

    const quantity = parseInt(quantityInput, 10)
    if (!Number.isFinite(quantity) || quantity < 0) {
      setError('Укажите фактическое количество — целое число от 0')
      return
    }
    if (!lookup.exists && quantity === 0) {
      setError('Для нового баркода количество должно быть больше 0')
      return
    }

    setLoading(true)
    try {
      const result = await submitInventory({
        seller_id: Number(sellerId),
        barcode: barcode.trim(),
        quantity,
        warehouse_ids: warehouseIds,
        cell_mode: lookup.exists ? 'auto' : cellMode,
        cell_id: !lookup.exists && cellMode === 'manual' ? Number(cellId) : null,
        name: productName,
      })
      setSessionCount((value) => value + 1)
      setVerifyModal({
        kind: result.verified ? 'ok' : 'error',
        result,
      })
      if (result.print_cell_label && result.cell_label) {
        setLabelPrompt(result.cell_label)
      }
      resetBarcodeForm()
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
            Фактический пересчёт на фулфилменте → остаток в CRM → выбранные склады FBS в ЛК WB
          </p>
        </div>
        <Link to="/warehouse" className="btn btn--secondary inventory-btn">
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
                <button
                  type="button"
                  className="btn btn--secondary inventory-btn inventory-btn--compact"
                  disabled={!sellerId || loading}
                  onClick={() => void handleSyncWarehouses()}
                >
                  Загрузить из WB
                </button>
              </div>
              {warehouses.length === 0 ? (
                <p className="inventory-hint">Выберите селлера и загрузите склады</p>
              ) : (
                <ul className="inventory-warehouse-list">
                  {warehouses.filter((wh) => wh.is_enabled).map((wh) => (
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
          <button
            type="button"
            className="btn btn--danger inventory-btn inventory-btn--large"
            disabled={!sellerId || warehouseIds.length < 1 || loading}
            onClick={startSession}
          >
            Начать инвентаризацию
          </button>
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
                <span className="inventory-session__count">Позиций: {sessionCount}</span>
                <button
                  type="button"
                  className="btn btn--danger inventory-btn"
                  onClick={finishSession}
                >
                  Завершить инвентаризацию
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
                  placeholder="Наведите сканер и отсканируйте баркод"
                  autoComplete="off"
                  autoFocus
                  inputMode="numeric"
                />
              </label>
              <button
                type="button"
                className="btn btn--secondary inventory-btn inventory-btn--lookup"
                disabled={loading || !barcode.trim()}
                onClick={() => void handleLookup()}
              >
                Найти товар
              </button>
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
                      {cellMode === 'manual' && cellId && (
                        <div className="inventory-cell-badge inventory-cell-badge--inline">
                          <span className="inventory-cell-badge__label">Выбрана</span>
                          <span className="inventory-cell-badge__number">
                            №{cells.find((cell) => cell.id === cellId)?.number}
                          </span>
                        </div>
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
                    Распечатать номер ячейки
                  </button>
                )}

                <label className="inventory-field">
                  Фактическое количество на фулфилменте
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
                  {loading ? 'Обработка…' : 'Провести инвентаризацию'}
                </button>
              </div>
            )}
          </form>
        </>
      )}

      {verifyModal && (
        <div className="inventory-modal-backdrop" onClick={closeVerifyModal}>
          <div
            className={`inventory-modal inventory-modal--${verifyModal.kind}`}
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
          >
            <h2>
              {verifyModal.kind === 'ok'
                ? 'Сверка успешна'
                : 'Расхождение с ЛК WB'}
            </h2>
            <p>
              Баркод <code>{verifyModal.result.product.barcode}</code> · фулфилмент:{' '}
              <strong>{verifyModal.result.fulfillment_quantity} шт.</strong>
            </p>

            {verifyModal.kind === 'ok' ? (
              <div className="inventory-modal__ok">
                <p>Остатки в ЛК WB совпадают с отправленными данными.</p>
                <table className="inventory-modal__table">
                  <thead>
                    <tr>
                      <th>Склад FBS</th>
                      <th>В ЛК WB</th>
                    </tr>
                  </thead>
                  <tbody>
                    {verifyModal.result.warehouses.map((row) => (
                      <tr key={row.warehouse_id}>
                        <td>{row.warehouse_name}</td>
                        <td><strong>{row.wb_actual} шт.</strong></td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr>
                      <td>Итого</td>
                      <td><strong>{verifyModal.result.wb_total_actual} шт.</strong></td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            ) : (
              <div className="inventory-modal__error">
                <table className="inventory-modal__table">
                  <thead>
                    <tr>
                      <th>Склад FBS</th>
                      <th>Отправили</th>
                      <th>Факт в ЛК WB</th>
                      <th>Разница</th>
                    </tr>
                  </thead>
                  <tbody>
                    {verifyModal.result.warehouses.map((row) => (
                      <tr key={row.warehouse_id}>
                        <td>{row.warehouse_name}</td>
                        <td>{row.sent_amount}</td>
                        <td>{row.wb_actual}</td>
                        <td className={row.difference !== 0 ? 'inventory-modal__diff' : ''}>
                          {row.difference > 0 ? `+${row.difference}` : row.difference}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr>
                      <td>Итого</td>
                      <td>{verifyModal.result.wb_total_sent}</td>
                      <td>{verifyModal.result.wb_total_actual}</td>
                      <td className="inventory-modal__diff">
                        {verifyModal.result.wb_total_difference > 0
                          ? `+${verifyModal.result.wb_total_difference}`
                          : verifyModal.result.wb_total_difference}
                      </td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            )}

            <button
              type="button"
              className="btn btn--primary inventory-btn inventory-btn--large inventory-modal__close"
              onClick={closeVerifyModal}
            >
              Продолжить
            </button>
          </div>
        </div>
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
    </div>
  )
}
