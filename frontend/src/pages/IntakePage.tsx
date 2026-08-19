import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import {
  fetchFreeCells,
  fetchIntakeHistory,
  fetchSellers,
  lookupBarcode,
  submitIntake,
  type Cell,
  type IntakeHistoryItem,
  type IntakeLookup,
  type Seller,
} from '../api/warehouse'
import './IntakePage.css'

export function IntakePage() {
  const barcodeRef = useRef<HTMLInputElement>(null)
  const [sellers, setSellers] = useState<Seller[]>([])
  const [cells, setCells] = useState<Cell[]>([])
  const [history, setHistory] = useState<IntakeHistoryItem[]>([])
  const [sellerId, setSellerId] = useState<number | ''>('')
  const [barcode, setBarcode] = useState('')
  const [quantity, setQuantity] = useState(1)
  const [productName, setProductName] = useState('')
  const [cellMode, setCellMode] = useState<'auto' | 'manual'>('auto')
  const [cellId, setCellId] = useState<number | ''>('')
  const [lookup, setLookup] = useState<IntakeLookup | null>(null)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [loading, setLoading] = useState(false)

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
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка загрузки')
    }
  }, [])

  useEffect(() => {
    loadInitial()
    barcodeRef.current?.focus()
  }, [loadInitial])

  async function handleLookup() {
    setError('')
    setSuccess('')
    if (!sellerId || !barcode.trim()) {
      setError('Выберите селлера и отсканируйте баркод')
      return
    }
    setLoading(true)
    try {
      const result = await lookupBarcode(Number(sellerId), barcode.trim())
      setLookup(result)
      if (!result.exists) {
        setCellMode('auto')
        setCellId('')
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

    if (!sellerId || !barcode.trim()) {
      setError('Укажите селлера и баркод')
      return
    }
    if (!lookup) {
      setError('Сначала отсканируйте баркод (Enter)')
      return
    }

    setLoading(true)
    try {
      const result = await submitIntake({
        seller_id: Number(sellerId),
        barcode: barcode.trim(),
        quantity,
        cell_mode: lookup.exists ? 'auto' : cellMode,
        cell_id: !lookup.exists && cellMode === 'manual' ? Number(cellId) : null,
        name: productName,
      })
      setSuccess(
        `${result.message} Ячейка №${result.product.cell_number}, остаток: ${result.product.quantity} шт.${
          result.product.requires_marking ? ' · Товар с Честным знаком' : ''
        }`,
      )
      setBarcode('')
      setLookup(null)
      setQuantity(1)
      setProductName('')
      setCellId('')
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
    setError('')
    setSuccess('')
    barcodeRef.current?.focus()
  }

  return (
    <>
      <header className="topbar">
        <div>
          <h1>Приёмка товара</h1>
          <p>Сканируйте баркод → введите количество → подтвердите приёмку</p>
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
                  setLookup(null)
                }}
                required
              >
                <option value="">— выберите —</option>
                {sellers.map((s) => (
                  <option key={s.id} value={s.id}>{s.company_name}</option>
                ))}
              </select>
              {sellers.length === 0 && (
                <span className="intake-hint">Добавьте селлера в админке: /admin</span>
              )}
            </label>

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
              />
            </label>

            <button
              type="button"
              className="btn btn--secondary"
              onClick={handleLookup}
              disabled={loading}
            >
              {loading ? 'Поиск…' : 'Найти товар (Enter)'}
            </button>

            {lookup?.exists && lookup.product && (
              <div className="intake-info intake-info--exists">
                <h3>Товар найден</h3>
                <p><strong>Ячейка:</strong> №{lookup.product.cell_number}</p>
                <p><strong>Текущий остаток:</strong> {lookup.product.quantity} шт.</p>
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

                {lookup.marking?.requires_marking && (
                  <p className="intake-marking intake-marking--required">
                    WB: товар подлежит обязательной маркировке «Честный знак»
                    {lookup.marking.title ? ` — ${lookup.marking.title}` : ''}
                  </p>
                )}
                {lookup.marking?.warning && (
                  <p className="intake-marking intake-marking--warning">{lookup.marking.warning}</p>
                )}
                {!lookup.marking?.requires_marking && lookup.marking?.wb_found && (
                  <p className="intake-marking intake-marking--ok">WB: маркировка ЧЗ не требуется</p>
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
                    Автоматически (свободная ячейка)
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

            {lookup && (
              <>
                <label className="intake-field intake-field--quantity">
                  Количество
                  <input
                    type="number"
                    min={1}
                    value={quantity}
                    onChange={(e) => setQuantity(Math.max(1, Number(e.target.value)))}
                    required
                  />
                </label>

                <div className="intake-actions">
                  <button type="submit" className="btn btn--primary" disabled={loading}>
                    {loading ? 'Сохранение…' : 'Принять на склад'}
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
    </>
  )
}
