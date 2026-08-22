import { useCallback, useEffect, useState } from 'react'
import {
  fetchAllCells,
  fetchProductCellLabel,
  fetchSellerProducts,
  fetchSellers,
  moveProductToCell,
  refreshSellerProductsFromWb,
  type Cell,
  type CellLabelData,
  type Product,
  type Seller,
} from '../api/warehouse'
import { CellLabelPrompt } from '../components/CellLabelPrompt'
import { printCellLabel } from '../utils/cellLabelPrint'
import './CellInventoryPage.css'

export function CellInventoryPage() {
  const [sellers, setSellers] = useState<Seller[]>([])
  const [sellerId, setSellerId] = useState<number | ''>('')
  const [products, setProducts] = useState<Product[]>([])
  const [cells, setCells] = useState<Cell[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [moveProductId, setMoveProductId] = useState<number | null>(null)
  const [moveCellId, setMoveCellId] = useState<number | ''>('')
  const [labelPrompt, setLabelPrompt] = useState<CellLabelData | null>(null)
  const [refreshing, setRefreshing] = useState(false)

  useEffect(() => {
    fetchSellers()
      .then((data) => {
        setSellers(data)
        if (data.length === 1) setSellerId(data[0].id)
      })
      .catch((err) => setError(err instanceof Error ? err.message : 'Ошибка загрузки'))
  }, [])

  useEffect(() => {
    if (!sellerId) {
      setCells([])
      return
    }
    fetchAllCells(Number(sellerId))
      .then(setCells)
      .catch(() => setCells([]))
  }, [sellerId])

  const loadProducts = useCallback(async () => {
    if (!sellerId) {
      setProducts([])
      return
    }
    setLoading(true)
    setError('')
    try {
      setProducts(await fetchSellerProducts(Number(sellerId)))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка загрузки товаров')
    } finally {
      setLoading(false)
    }
  }, [sellerId])

  useEffect(() => {
    loadProducts()
  }, [loadProducts])

  async function handleRefreshFromWb() {
    if (!sellerId) return
    setRefreshing(true)
    setError('')
    setSuccess('')
    try {
      const result = await refreshSellerProductsFromWb(Number(sellerId))
      setProducts(result.products)
      setSuccess(result.message)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка обновления из WB')
    } finally {
      setRefreshing(false)
    }
  }

  async function handlePrint(productId: number) {
    setError('')
    try {
      const label = await fetchProductCellLabel(productId)
      printCellLabel(label, true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка печати')
    }
  }

  async function handleMoveSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!moveProductId || !moveCellId) return
    setLoading(true)
    setError('')
    setSuccess('')
    try {
      const result = await moveProductToCell(moveProductId, Number(moveCellId))
      setSuccess(result.message)
      setMoveProductId(null)
      setMoveCellId('')
      await loadProducts()
      if (sellerId) {
        const cellsData = await fetchAllCells(Number(sellerId))
        setCells(cellsData)
      }
      if (result.print_cell_label && result.cell_label) {
        setLabelPrompt(result.cell_label)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка переноса')
    } finally {
      setLoading(false)
    }
  }

  const movingProduct = products.find((p) => p.id === moveProductId)

  return (
    <>
      <header className="topbar">
        <div>
          <h1>Ячейки склада</h1>
          <p>Список товаров по селлеру · печать этикеток · перенос в другую ячейку</p>
        </div>
      </header>

      {error && <div className="alert alert--error">{error}</div>}
      {success && <div className="alert alert--success">{success}</div>}

      <section className="panel cell-inventory-toolbar">
        <label className="cell-inventory-field">
          Селлер
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
      </section>

      <section className="panel">
        <div className="cell-inventory-section-head">
          <h2 className="section-title">
            Товары {sellerId ? `(${products.length})` : ''}
          </h2>
          {sellerId && products.length > 0 && (
            <button
              type="button"
              className="btn btn--secondary"
              disabled={refreshing || loading}
              onClick={handleRefreshFromWb}
            >
              {refreshing ? 'Обновление из WB…' : 'Обновить из WB'}
            </button>
          )}
        </div>
        {!sellerId ? (
          <p className="cell-inventory-empty">Выберите селлера</p>
        ) : loading && products.length === 0 ? (
          <p className="cell-inventory-empty">Загрузка…</p>
        ) : products.length === 0 ? (
          <p className="cell-inventory-empty">Нет товаров на складе</p>
        ) : (
          <table className="cell-inventory-table">
            <thead>
              <tr>
                <th>Ячейка</th>
                <th>Баркод</th>
                <th>Название</th>
                <th>Остаток</th>
                <th>Действия</th>
              </tr>
            </thead>
            <tbody>
              {products.map((product) => (
                <tr key={product.id}>
                  <td><strong>№{product.cell_number}</strong></td>
                  <td>{product.barcode}</td>
                  <td>{product.name || '—'}</td>
                  <td>{product.quantity} шт.</td>
                  <td className="cell-inventory-actions">
                    <button
                      type="button"
                      className="btn btn--secondary btn--small"
                      onClick={() => handlePrint(product.id)}
                    >
                      Печать этикетки
                    </button>
                    <button
                      type="button"
                      className="btn btn--ghost btn--small"
                      onClick={() => {
                        setMoveProductId(product.id)
                        setMoveCellId('')
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
      </section>

      {moveProductId && movingProduct && (
        <div className="cell-inventory-modal-backdrop" role="presentation" onClick={() => setMoveProductId(null)}>
          <div className="cell-inventory-modal" role="dialog" onClick={(e) => e.stopPropagation()}>
            <h3>Перенос в другую ячейку</h3>
            <p>
              Баркод: <strong>{movingProduct.barcode}</strong>
              <br />
              Сейчас: <strong>№{movingProduct.cell_number}</strong>
            </p>
            <form onSubmit={handleMoveSubmit}>
              <label className="cell-inventory-field">
                Новая ячейка
                <select
                  value={moveCellId}
                  onChange={(e) => setMoveCellId(e.target.value ? Number(e.target.value) : '')}
                  required
                >
                  <option value="">— выберите —</option>
                  {cells
                    .filter((c) => c.id !== movingProduct.cell)
                    .map((c) => (
                      <option key={c.id} value={c.id}>
                        №{c.number}{c.is_occupied ? ' (занята)' : ' (свободна)'}
                      </option>
                    ))}
                </select>
              </label>
              <div className="cell-inventory-modal__actions">
                <button type="submit" className="btn btn--primary" disabled={loading}>
                  Перенести
                </button>
                <button type="button" className="btn btn--secondary" onClick={() => setMoveProductId(null)}>
                  Отмена
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {labelPrompt && (
        <CellLabelPrompt label={labelPrompt} onClose={() => setLabelPrompt(null)} />
      )}
    </>
  )
}
