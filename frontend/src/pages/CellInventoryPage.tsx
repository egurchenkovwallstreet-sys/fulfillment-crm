import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  fetchAllCells,
  fetchCellDetail,
  fetchProductCellLabel,
  fetchSellerProducts,
  fetchSellers,
  moveProductToCell,
  refreshSellerProductsFromWb,
  type Cell,
  type CellDetail,
  type CellLabelData,
  type Product,
  type Seller,
} from '../api/warehouse'
import { CellLabelPrompt } from '../components/CellLabelPrompt'
import { ProductPhotoThumb } from '../components/ProductPhotoThumb'
import { printCellLabel } from '../utils/cellLabelPrint'
import './CellInventoryPage.css'

export function CellInventoryPage() {
  const [sellers, setSellers] = useState<Seller[]>([])
  const [sellerId, setSellerId] = useState<number | ''>('')
  const [products, setProducts] = useState<Product[]>([])
  const [cells, setCells] = useState<Cell[]>([])
  const [barcodeQuery, setBarcodeQuery] = useState('')
  const [cellQuery, setCellQuery] = useState('')
  const [cellDetail, setCellDetail] = useState<CellDetail | null>(null)
  const [cellSearchLoading, setCellSearchLoading] = useState(false)
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

  async function handleCellSearch(e?: React.FormEvent) {
    e?.preventDefault()
    if (!sellerId || !cellQuery.trim()) return
    setCellSearchLoading(true)
    setError('')
    setCellDetail(null)
    try {
      setCellDetail(await fetchCellDetail(Number(sellerId), cellQuery.trim()))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ячейка не найдена')
    } finally {
      setCellSearchLoading(false)
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

  const filteredProducts = useMemo(() => {
    const query = barcodeQuery.trim()
    if (!query) return products
    return products.filter((product) => product.barcode.includes(query))
  }, [products, barcodeQuery])

  return (
    <>
      <header className="topbar">
        <div>
          <h1>Ячейки склада</h1>
          <p>Список товаров по селлеру · поиск по ячейке · печать этикеток · перенос</p>
        </div>
      </header>

      {error && <div className="alert alert--error">{error}</div>}
      {success && <div className="alert alert--success">{success}</div>}

      <section className="panel cell-inventory-toolbar">
        <label className="cell-inventory-field">
          Селлер
          <select
            value={sellerId}
            onChange={(e) => {
              setSellerId(e.target.value ? Number(e.target.value) : '')
              setBarcodeQuery('')
              setCellQuery('')
              setCellDetail(null)
            }}
          >
            <option value="">— выберите —</option>
            {sellers.map((s) => (
              <option key={s.id} value={s.id}>{s.company_name}</option>
            ))}
          </select>
        </label>
        {sellerId && (
          <form className="cell-inventory-field cell-inventory-field--search" onSubmit={handleCellSearch}>
            <label htmlFor="cell-search">Поиск по ячейке</label>
            <div className="cell-inventory-search-row">
              <input
                id="cell-search"
                type="search"
                value={cellQuery}
                onChange={(e) => setCellQuery(e.target.value)}
                placeholder="Номер ячейки, например 42"
                autoComplete="off"
              />
              <button type="submit" className="btn btn--primary" disabled={cellSearchLoading || !cellQuery.trim()}>
                {cellSearchLoading ? '…' : 'Найти'}
              </button>
            </div>
          </form>
        )}
        {sellerId && (
          <label className="cell-inventory-field cell-inventory-field--search">
            Поиск по баркоду
            <input
              type="search"
              value={barcodeQuery}
              onChange={(e) => setBarcodeQuery(e.target.value)}
              placeholder="Введите баркод или часть номера"
              autoComplete="off"
            />
          </label>
        )}
      </section>

      {cellDetail && (
        <section className="panel cell-detail-panel">
          <div className="cell-detail-panel__head">
            <h2 className="section-title">Ячейка №{cellDetail.cell.number}</h2>
            <button type="button" className="btn btn--ghost btn--small" onClick={() => setCellDetail(null)}>
              Закрыть
            </button>
          </div>
          {!cellDetail.product ? (
            <p className="cell-inventory-empty">Ячейка свободна — товар не привязан</p>
          ) : (
            <div className="cell-detail-grid">
              <div className="cell-detail-photo">
                <ProductPhotoThumb
                  url={cellDetail.product.photo_url ?? ''}
                  alt={cellDetail.product.name || cellDetail.product.barcode}
                  size="detail"
                />
                <p className="cell-detail-photo-hint">Нажмите на фото для увеличения</p>
              </div>
              <dl className="cell-detail-facts">
                <div>
                  <dt>Баркод</dt>
                  <dd>{cellDetail.product.barcode}</dd>
                </div>
                <div>
                  <dt>Артикул</dt>
                  <dd>{cellDetail.product.vendor_code || '—'}</dd>
                </div>
                <div>
                  <dt>Размер (EU / тех.)</dt>
                  <dd>{cellDetail.product.tech_size || '—'}</dd>
                </div>
                <div>
                  <dt>Размер (RU)</dt>
                  <dd>{cellDetail.product.wb_size || '—'}</dd>
                </div>
                <div>
                  <dt>Название</dt>
                  <dd>{cellDetail.product.name || '—'}</dd>
                </div>
                <div>
                  <dt>Остаток</dt>
                  <dd>{cellDetail.product.quantity} шт.</dd>
                </div>
                {cellDetail.product.wb_nm_id && (
                  <div>
                    <dt>nmID WB</dt>
                    <dd>{cellDetail.product.wb_nm_id}</dd>
                  </div>
                )}
              </dl>
            </div>
          )}
        </section>
      )}

      <section className="panel">
        <div className="cell-inventory-section-head">
          <h2 className="section-title">
            Товары {sellerId ? `(${filteredProducts.length}${barcodeQuery.trim() ? ` из ${products.length}` : ''})` : ''}
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
        ) : filteredProducts.length === 0 ? (
          <p className="cell-inventory-empty">
            {barcodeQuery.trim() ? 'Ничего не найдено по баркоду' : 'Нет товаров на складе'}
          </p>
        ) : (
          <table className="cell-inventory-table">
            <thead>
              <tr>
                <th>Фото</th>
                <th>Ячейка</th>
                <th>Баркод</th>
                <th>Артикул</th>
                <th>Размер</th>
                <th>Название</th>
                <th>Остаток</th>
                <th>Действия</th>
              </tr>
            </thead>
            <tbody>
              {filteredProducts.map((product) => (
                <tr key={product.id}>
                  <td>
                    <ProductPhotoThumb url={product.photo_url ?? ''} alt={product.name || product.barcode} />
                  </td>
                  <td><strong>№{product.cell_number}</strong></td>
                  <td>{product.barcode}</td>
                  <td>{product.vendor_code || '—'}</td>
                  <td>
                    <strong className="cell-inventory-size">
                      {product.tech_size || product.wb_size || '—'}
                    </strong>
                  </td>
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
