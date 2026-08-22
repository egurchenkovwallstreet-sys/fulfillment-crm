import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import {
  fetchFreeCells,
  fetchIntakeHistory,
  fetchSellers,
  lookupBarcode,
  submitIntake,
  type Cell,
  type CellLabelData,
  type IntakeHistoryItem,
  type IntakeLookup,
  type Seller,
  type StockMode,
} from '../api/warehouse'
import { fetchSellerWarehouses, syncSellerWarehouses, type SellerWarehouse } from '../api/sellers'
import { CellLabelPrompt } from '../components/CellLabelPrompt'
import './IntakePage.css'

export function IntakePage() {
  const barcodeRef = useRef<HTMLInputElement>(null)
  const [sellers, setSellers] = useState<Seller[]>([])
  const [cells, setCells] = useState<Cell[]>([])
  const [history, setHistory] = useState<IntakeHistoryItem[]>([])
  const [warehouses, setWarehouses] = useState<SellerWarehouse[]>([])
  const [sellerId, setSellerId] = useState<number | ''>('')
  const [warehouseId, setWarehouseId] = useState<number | ''>('')
  const [stockMode, setStockMode] = useState<StockMode>('intake')
  const [verifiedStockMatch, setVerifiedStockMatch] = useState(false)
  const [barcode, setBarcode] = useState('')
  const [quantityInput, setQuantityInput] = useState('1')
  const [productName, setProductName] = useState('')
  const [cellMode, setCellMode] = useState<'auto' | 'manual'>('auto')
  const [cellId, setCellId] = useState<number | ''>('')
  const [lookup, setLookup] = useState<IntakeLookup | null>(null)
  const [labelPrompt, setLabelPrompt] = useState<CellLabelData | null>(null)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [loading, setLoading] = useState(false)

  const loadWarehouses = useCallback(async (id: number) => {
    try {
      const data = await fetchSellerWarehouses(id)
      setWarehouses(data)
      const enabled = data.filter((w) => w.is_enabled)
      if (enabled.length === 1) {
        setWarehouseId(enabled[0].id)
      }
    } catch {
      setWarehouses([])
    }
  }, [])

  const loadInitial = useCallback(async () => {
    try {
      const [sellersData, cellsData, historyData] = await Promise.all([
        fetchSellers(),
        fetchFreeCells(),
        fetchIntakeHistory(),
      ])
      setSellers(sellersData)
      setCells(cellsData)
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
      return
    }
    loadWarehouses(Number(sellerId))
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
    if (!sellerId || !warehouseId || !barcode.trim()) {
      setError('Выберите селлера, склад FBS и отсканируйте баркод')
      return
    }
    setLoading(true)
    try {
      const result = await lookupBarcode(Number(sellerId), barcode.trim(), Number(warehouseId))
      setLookup(result)
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

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError('')
    setSuccess('')

    if (!sellerId || !warehouseId || !barcode.trim()) {
      setError('Укажите селлера, склад FBS и баркод')
      return
    }
    if (!lookup) {
      setError('Сначала отсканируйте баркод (Enter)')
      return
    }
    if (stockMode === 'sync_from_wb' && !verifiedStockMatch) {
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

    setLoading(true)
    try {
      const result = await submitIntake({
        seller_id: Number(sellerId),
        wb_warehouse_id: Number(warehouseId),
        barcode: barcode.trim(),
        quantity,
        stock_mode: stockMode,
        verified_stock_match: stockMode === 'sync_from_wb' ? verifiedStockMatch : false,
        cell_mode: lookup.exists ? 'auto' : cellMode,
        cell_id: !lookup.exists && cellMode === 'manual' ? Number(cellId) : null,
        name: productName,
      })
      setSuccess(
        `${result.message} Ячейка №${result.product.cell_number}, остаток CRM: ${result.product.quantity} шт.${
          result.product.requires_marking ? ' · Товар с Честным знаком' : ''
        }`,
      )
      if (result.print_cell_label && result.cell_label) {
        setLabelPrompt(result.cell_label)
      }
      setBarcode('')
      setLookup(null)
      setQuantityInput('1')
      setProductName('')
      setCellId('')
      setVerifiedStockMatch(false)
      const [cellsData, historyData] = await Promise.all([
        fetchFreeCells(),
        fetchIntakeHistory(),
      ])
      setCells(cellsData)
      setHistory(historyData)
      barcodeRef.current?.focus()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка приёмки')
    } finally {
      setLoading(false)
    }
  }

  function resetForm() {
    setBarcode('')
    setLookup(null)
    setVerifiedStockMatch(false)
    setError('')
    setSuccess('')
    barcodeRef.current?.focus()
  }

  const isSyncMode = stockMode === 'sync_from_wb'
  const enabledWarehouses = warehouses.filter((w) => w.is_enabled)

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

            <div className="intake-warehouses">
              <div className="intake-warehouses__head">
                <span className="intake-field__label">Склад FBS (точка отгрузки WB)</span>
                <button
                  type="button"
                  className="btn btn--secondary btn--small"
                  onClick={handleSyncWarehouses}
                  disabled={loading || !sellerId}
                >
                  Загрузить из WB
                </button>
              </div>
              {sellerId && enabledWarehouses.length === 0 && (
                <p className="intake-hint">Нажмите «Загрузить из WB», чтобы получить склады</p>
              )}
              <select
                value={warehouseId}
                onChange={(e) => {
                  setWarehouseId(e.target.value ? Number(e.target.value) : '')
                  setLookup(null)
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

            <fieldset className="intake-stock-mode">
              <legend>Остатки</legend>
              <label>
                <input
                  type="radio"
                  name="stockMode"
                  checked={stockMode === 'intake'}
                  onChange={() => {
                    setStockMode('intake')
                    setVerifiedStockMatch(false)
                    setLookup(null)
                  }}
                />
                <strong>Приёмка</strong> — принять на склад CRM и добавить в ЛК WB
              </label>
              <label>
                <input
                  type="radio"
                  name="stockMode"
                  checked={stockMode === 'sync_from_wb'}
                  onChange={() => {
                    setStockMode('sync_from_wb')
                    setVerifiedStockMatch(false)
                    setLookup(null)
                  }}
                />
                <strong>Сверка с WB</strong> — установить остаток CRM по ЛК WB
              </label>
            </fieldset>

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
                disabled={!warehouseId}
              />
            </label>

            <button
              type="button"
              className="btn btn--secondary"
              onClick={handleLookup}
              disabled={loading || !warehouseId}
            >
              {loading ? 'Поиск…' : 'Найти товар (Enter)'}
            </button>

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

            {lookup && !lookup.exists && (
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

            {lookup && isSyncMode && (
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
                    Количество (факт при приёмке)
                    <input
                      type="text"
                      inputMode="numeric"
                      pattern="[0-9]*"
                      value={quantityInput}
                      onChange={(e) => setQuantityInput(e.target.value.replace(/\D/g, ''))}
                      placeholder="1"
                      required
                    />
                  </label>
                )}

                {isSyncMode && lookup.wb_stock != null && (
                  <p className="intake-sync-qty">
                    Будет установлено в CRM: <strong>{lookup.wb_stock} шт.</strong> (из ЛК WB)
                  </p>
                )}

                <div className="intake-actions">
                  <button
                    type="submit"
                    className="btn btn--primary"
                    disabled={loading || (isSyncMode && !verifiedStockMatch)}
                  >
                    {loading
                      ? 'Сохранение…'
                      : isSyncMode
                        ? 'Установить остаток из WB'
                        : 'Принять на склад'}
                  </button>
                  <button type="button" className="btn btn--secondary" onClick={resetForm}>
                    Сбросить
                  </button>
                </div>
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
    </>
  )
}
