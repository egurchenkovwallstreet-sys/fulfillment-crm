import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  deleteCell,
  fetchAllCells,
  fetchCellDetail,
  fetchProductCellLabel,
  fetchProductWbStocks,
  fetchSellerProducts,
  fetchSellers,
  mergeDuplicateCells,
  moveProductToCell,
  mergeDuplicateCells,
  refreshSellerProductsFromWb,
  type Cell,
  type CellDetail,
  type CellLabelData,
  type Product,
  type Seller,
  type WbWarehouseStockLine,
} from '../api/warehouse'
import { CellLabelPrompt } from '../components/CellLabelPrompt'
import { ProductPhotoThumb } from '../components/ProductPhotoThumb'
import { WbBarcodeHint } from '../components/WbBarcodeHint'
import { useAuth } from '../context/AuthContext'
import { useCrmNotice } from '../context/CrmNoticeContext'
import { useMarketplace } from '../context/MarketplaceContext'
import { printCellLabel } from '../utils/cellLabelPrint'
import { hintWrapProps, uiHint } from '../utils/uiHint'
import './CellInventoryPage.css'

type DeleteCellTarget = {
  cellId: number
  cellNumber: string
  product: Product | null
}

function duplicateGroupMembers(product: Product, catalog: Product[]): Product[] {
  const ids = new Set<number>([product.id, ...(product.duplicate_product_ids ?? [])])
  return catalog.filter((p) => ids.has(p.id))
}

function WbStocksLines({
  lines,
  error,
  loading = false,
  compact = false,
}: {
  lines?: WbWarehouseStockLine[]
  error?: string
  loading?: boolean
  compact?: boolean
}) {
  if (loading) {
    return <span className="cell-wb-stocks cell-wb-stocks--muted">WB…</span>
  }
  if (error) {
    return <span className="cell-wb-stocks cell-wb-stocks--error">{error}</span>
  }
  if (!lines || lines.length === 0) {
    return <span className="cell-wb-stocks cell-wb-stocks--muted">WB: —</span>
  }
  return (
    <ul className={`cell-wb-stocks${compact ? ' cell-wb-stocks--compact' : ''}`}>
      {lines.map((line) => (
        <li key={line.warehouse_id}>
          <span className="cell-wb-stocks__name">{line.warehouse_name}</span>
          <span className="cell-wb-stocks__qty">{line.quantity} шт.</span>
        </li>
      ))}
    </ul>
  )
}

export function CellInventoryPage() {
  const { isAdmin } = useAuth()
  const { marketplace } = useMarketplace()
  const isWb = marketplace === 'wb'
  const { showSuccess, showError } = useCrmNotice()
  const [sellers, setSellers] = useState<Seller[]>([])
  const [sellerId, setSellerId] = useState<number | ''>('')
  const [products, setProducts] = useState<Product[]>([])
  const [cells, setCells] = useState<Cell[]>([])
  const [barcodeQuery, setBarcodeQuery] = useState('')
  const [cellQuery, setCellQuery] = useState('')
  const [cellDetail, setCellDetail] = useState<CellDetail | null>(null)
  const [cellSearchLoading, setCellSearchLoading] = useState(false)
  const [loading, setLoading] = useState(false)
  const [moveProductId, setMoveProductId] = useState<number | null>(null)
  const [moveCellId, setMoveCellId] = useState<number | ''>('')
  const [labelPrompt, setLabelPrompt] = useState<CellLabelData | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<DeleteCellTarget | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [wbStocksByBarcode, setWbStocksByBarcode] = useState<
    Record<string, WbWarehouseStockLine[]>
  >({})
  const [wbStocksLoading, setWbStocksLoading] = useState(false)
  const [wbStocksError, setWbStocksError] = useState('')
  const [mergeAnchor, setMergeAnchor] = useState<Product | null>(null)
  const [mergeTargetId, setMergeTargetId] = useState<number | ''>('')
  const [merging, setMerging] = useState(false)

  useEffect(() => {
    fetchSellers()
      .then((data) => {
        setSellers(data)
        if (data.length === 1) setSellerId(data[0].id)
      })
      .catch((err) => showError('Загрузка', err instanceof Error ? err.message : 'Ошибка загрузки'))
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
    try {
      setProducts(await fetchSellerProducts(Number(sellerId)))
    } catch (err) {
      showError('Товары', err instanceof Error ? err.message : 'Ошибка загрузки товаров')
    } finally {
      setLoading(false)
    }
  }, [sellerId, showError])

  useEffect(() => {
    loadProducts()
  }, [loadProducts])

  async function handleRefreshFromWb() {
    if (!sellerId) return
    setRefreshing(true)
    try {
      const result = await refreshSellerProductsFromWb(Number(sellerId))
      await loadProducts()
      showSuccess('Каталог', result.message)
    } catch (err) {
      showError('Каталог', err instanceof Error ? err.message : 'Ошибка обновления из WB')
    } finally {
      setRefreshing(false)
    }
  }

  async function handleCellSearch(e?: React.FormEvent) {
    e?.preventDefault()
    if (!sellerId || !cellQuery.trim()) return
    setCellSearchLoading(true)
    setCellDetail(null)
    try {
      setCellDetail(await fetchCellDetail(Number(sellerId), cellQuery.trim()))
    } catch (err) {
      showError('Ячейка', err instanceof Error ? err.message : 'Ячейка не найдена')
    } finally {
      setCellSearchLoading(false)
    }
  }

  async function handlePrint(productId: number) {
    try {
      const label = await fetchProductCellLabel(productId)
      printCellLabel(label, true)
    } catch (err) {
      showError('Печать', err instanceof Error ? err.message : 'Ошибка печати')
    }
  }

  async function handleMergeSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!sellerId || !mergeTargetId) return
    setMerging(true)
    try {
      await mergeDuplicateCells(Number(sellerId), Number(mergeTargetId))
      showSuccess(
        'Объединение',
        'Дубли объединены: остатки сложены, лишние ячейки удалены, джитины записаны как доп. баркоды.',
      )
      setMergeAnchor(null)
      setMergeTargetId('')
      await loadProducts()
      if (sellerId) {
        setCells(await fetchAllCells(Number(sellerId)))
      }
    } catch (err) {
      showError('Объединение', err instanceof Error ? err.message : 'Не удалось объединить')
    } finally {
      setMerging(false)
    }
  }

  async function handleMoveSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!moveProductId || !moveCellId) return
    setLoading(true)
    try {
      const result = await moveProductToCell(moveProductId, Number(moveCellId))
      showSuccess('Ячейка', result.message)
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
      showError('Перенос', err instanceof Error ? err.message : 'Ошибка переноса')
    } finally {
      setLoading(false)
    }
  }

  function openDeleteCellDialog(target: DeleteCellTarget) {
    setDeleteTarget(target)
  }

  async function handleDeleteCellConfirm() {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      const result = await deleteCell(deleteTarget.cellId)
      showSuccess('Ячейка', result.message)
      setDeleteTarget(null)
      if (cellDetail?.cell.id === deleteTarget.cellId) {
        setCellDetail(null)
        setCellQuery('')
      }
      await loadProducts()
      if (sellerId) {
        setCells(await fetchAllCells(Number(sellerId)))
      }
    } catch (err) {
      showError('Ячейка', err instanceof Error ? err.message : 'Не удалось удалить ячейку')
    } finally {
      setDeleting(false)
    }
  }

  const movingProduct = products.find((p) => p.id === moveProductId)

  const filteredProducts = useMemo(() => {
    const query = barcodeQuery.trim()
    if (!query) return products
    return products.filter((product) => product.barcode.includes(query))
  }, [products, barcodeQuery])

  useEffect(() => {
    if (!isWb || !sellerId || !barcodeQuery.trim() || filteredProducts.length === 0) {
      setWbStocksByBarcode({})
      setWbStocksError('')
      setWbStocksLoading(false)
      return
    }

    const barcodes = filteredProducts.map((product) => product.barcode)
    let cancelled = false
    const timer = window.setTimeout(() => {
      setWbStocksLoading(true)
      setWbStocksError('')
      fetchProductWbStocks(Number(sellerId), barcodes)
        .then((result) => {
          if (cancelled) return
          setWbStocksByBarcode(result.wb_stocks_by_barcode || {})
          setWbStocksError(result.wb_stocks_error || '')
        })
        .catch((err) => {
          if (cancelled) return
          setWbStocksByBarcode({})
          setWbStocksError(err instanceof Error ? err.message : 'Ошибка остатков WB')
        })
        .finally(() => {
          if (!cancelled) setWbStocksLoading(false)
        })
    }, 350)

    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [isWb, sellerId, barcodeQuery, filteredProducts])

  const showWbStocksInTable = isWb && barcodeQuery.trim().length > 0

  const duplicateGroupCount = useMemo(() => {
    const seen = new Set<number>()
    let count = 0
    for (const product of products) {
      if (!product.has_duplicate_cells || product.duplicate_chrt_id == null) continue
      if (seen.has(product.duplicate_chrt_id)) continue
      seen.add(product.duplicate_chrt_id)
      count += 1
    }
    return count
  }, [products])

  const mergeGroupProducts = mergeAnchor
    ? duplicateGroupMembers(mergeAnchor, products)
    : []

  return (
    <>
      <header className="topbar">
        <div>
          <h1>Ячейки склада</h1>
          <p>Список товаров по селлеру · поиск по ячейке · печать этикеток · перенос</p>
        </div>
      </header>

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
              <span {...hintWrapProps('Найти ячейку по номеру и показать привязанный товар.')}>
                <button type="submit" className="btn btn--primary" disabled={cellSearchLoading || !cellQuery.trim()}>
                  {cellSearchLoading ? '…' : 'Найти'}
                </button>
              </span>
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
            <div className="cell-detail-panel__actions">
              {isAdmin && (
                <button
                  type="button"
                  className="btn btn--danger btn--small"
                  onClick={() =>
                    openDeleteCellDialog({
                      cellId: cellDetail.cell.id,
                      cellNumber: cellDetail.cell.number,
                      product: cellDetail.product,
                    })
                  }
                  {...uiHint('Удалить ячейку и привязанный товар без возможности восстановления.')}
                >
                  Удалить ячейку
                </button>
              )}
              <button type="button" className="btn btn--ghost btn--small" onClick={() => setCellDetail(null)} {...uiHint('Закрыть карточку ячейки и вернуться к списку.')}>
                Закрыть
              </button>
            </div>
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
                  <dd>
                    <WbBarcodeHint
                      displayCode={cellDetail.product.barcode}
                      primaryBarcode={cellDetail.product.barcode}
                      alternateBarcodes={cellDetail.product.alternate_barcodes}
                      wbSkuCodes={cellDetail.product.wb_sku_codes}
                      alwaysInteractive={isWb}
                    />
                  </dd>
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
                  <dt>Остаток CRM</dt>
                  <dd>{cellDetail.product.quantity} шт.</dd>
                </div>
                {isWb && (
                  <div className="cell-detail-facts__wb">
                    <dt>Остатки WB (FBS)</dt>
                    <dd>
                      <WbStocksLines
                        lines={cellDetail.wb_stocks}
                        error={cellDetail.wb_stocks_error}
                      />
                    </dd>
                  </div>
                )}
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
              {...uiHint('Обновить названия, фото и размеры товаров из каталога WB.')}
            >
              {refreshing ? 'Обновление из WB…' : 'Обновить из WB'}
            </button>
          )}
        </div>
        {isWb && duplicateGroupCount > 0 && (
          <p className="cell-inventory-dup-banner">
            Найдено групп с дублями (один размер WB в разных ячейках):{' '}
            <strong>{duplicateGroupCount}</strong>. Строки подсвечены — нажмите «Объединить».
          </p>
        )}
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
                <th>Остаток CRM</th>
                {showWbStocksInTable && <th>Остатки WB</th>}
                <th>Действия</th>
              </tr>
            </thead>
            <tbody>
              {filteredProducts.map((product) => (
                <tr
                  key={product.id}
                  className={product.has_duplicate_cells ? 'cell-inventory-row--duplicate' : undefined}
                >
                  <td>
                    <ProductPhotoThumb url={product.photo_url ?? ''} alt={product.name || product.barcode} />
                  </td>
                  <td className="cell-inventory-cell-col">
                    <strong>№{product.cell_number}</strong>
                    {product.has_duplicate_cells && (
                      <div className="cell-inventory-dup-meta">
                        <span className="cell-inventory-dup-meta__label">
                          Дубли:{' '}
                          {(product.duplicate_cell_numbers ?? [])
                            .map((num) => `№${num}`)
                            .join(', ')}
                        </span>
                        <button
                          type="button"
                          className="btn btn--warning btn--small"
                          onClick={() => {
                            setMergeAnchor(product)
                            setMergeTargetId(product.id)
                          }}
                          {...uiHint(
                            'Объединить все ячейки этого размера WB в одну: остатки суммируются, другие ячейки удаляются.',
                          )}
                        >
                          Объединить
                        </button>
                      </div>
                    )}
                  </td>
                  <td>
                    <WbBarcodeHint
                      displayCode={product.barcode}
                      primaryBarcode={product.barcode}
                      alternateBarcodes={product.alternate_barcodes}
                      wbSkuCodes={product.wb_sku_codes}
                      alwaysInteractive={isWb}
                    />
                  </td>
                  <td>{product.vendor_code || '—'}</td>
                  <td>
                    <strong className="cell-inventory-size">
                      {product.tech_size || product.wb_size || '—'}
                    </strong>
                  </td>
                  <td>{product.name || '—'}</td>
                  <td>{product.quantity} шт.</td>
                  {showWbStocksInTable && (
                    <td>
                      <WbStocksLines
                        compact
                        loading={wbStocksLoading}
                        error={wbStocksError || undefined}
                        lines={wbStocksByBarcode[product.barcode]}
                      />
                    </td>
                  )}
                  <td className="cell-inventory-actions">
                    <button
                      type="button"
                      className="btn btn--secondary btn--small"
                      onClick={() => handlePrint(product.id)}
                      {...uiHint('Напечатать этикетку ячейки для этого товара.')}
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
                      {...uiHint('Перенести товар в другую ячейку склада.')}
                    >
                      Перенести
                    </button>
                    {isAdmin && (
                      <button
                        type="button"
                        className="btn btn--danger btn--small"
                        onClick={() =>
                          openDeleteCellDialog({
                            cellId: product.cell,
                            cellNumber: product.cell_number,
                            product,
                          })
                        }
                        {...uiHint('Удалить ячейку вместе с этим товаром.')}
                      >
                        Удалить
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {mergeAnchor && mergeGroupProducts.length > 0 && (
        <div
          className="cell-inventory-modal-backdrop"
          role="presentation"
          onClick={() => !merging && setMergeAnchor(null)}
        >
          <div className="cell-inventory-modal" role="dialog" onClick={(e) => e.stopPropagation()}>
            <h3>Объединить дубли одного товара</h3>
            <p className="cell-inventory-merge-intro">
              Один размер WB разнесён по нескольким ячейкам. Выберите ячейку, которую оставляем — остальные
              будут удалены, остатки сложатся, баркоды джитинов станут доп. SKU.
            </p>
            <form onSubmit={(e) => void handleMergeSubmit(e)}>
              <ul className="cell-inventory-merge-options">
                {mergeGroupProducts.map((item) => (
                  <li key={item.id}>
                    <label className="cell-inventory-merge-option">
                      <input
                        type="radio"
                        name="merge-target"
                        value={item.id}
                        checked={mergeTargetId === item.id}
                        onChange={() => setMergeTargetId(item.id)}
                      />
                      <span>
                        <strong>№{item.cell_number}</strong>
                        {' · '}
                        <code>{item.barcode}</code>
                        {' · '}
                        {item.quantity} шт.
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
              <div className="cell-inventory-modal__actions">
                <button
                  type="submit"
                  className="btn btn--primary"
                  disabled={merging || !mergeTargetId}
                >
                  {merging ? 'Объединение…' : 'Объединить и удалить другие ячейки'}
                </button>
                <button
                  type="button"
                  className="btn btn--secondary"
                  disabled={merging}
                  onClick={() => setMergeAnchor(null)}
                >
                  Отмена
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

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
                <button type="submit" className="btn btn--primary" disabled={loading} {...uiHint('Переместить товар в выбранную ячейку и обновить привязку.')}>
                  Перенести
                </button>
                <button type="button" className="btn btn--secondary" onClick={() => setMoveProductId(null)} {...uiHint('Закрыть окно переноса без изменений.')}>
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

      {deleteTarget && (
        <div className="cell-inventory-modal-backdrop" role="presentation" onClick={() => !deleting && setDeleteTarget(null)}>
          <div className="cell-inventory-modal cell-inventory-modal--danger" role="dialog" onClick={(e) => e.stopPropagation()}>
            <h3>Удалить ячейку №{deleteTarget.cellNumber}?</h3>
            {deleteTarget.product ? (
              <p>
                Будет удалены ячейка и товар:
                <br />
                Баркод: <strong>{deleteTarget.product.barcode}</strong>
                <br />
                Остаток CRM: <strong>{deleteTarget.product.quantity} шт.</strong>
                <br />
                <span className="cell-inventory-delete-warning">
                  Позиции листов подбора и привязки к заказам будут сняты. Отменить нельзя.
                </span>
              </p>
            ) : (
              <p>
                Ячейка свободна — будет удалена только запись в CRM.
                <br />
                <span className="cell-inventory-delete-warning">Отменить нельзя.</span>
              </p>
            )}
            <div className="cell-inventory-modal__actions">
              <button
                type="button"
                className="btn btn--danger"
                disabled={deleting}
                onClick={() => void handleDeleteCellConfirm()}
              >
                {deleting ? 'Удаление…' : 'Удалить навсегда'}
              </button>
              <button
                type="button"
                className="btn btn--secondary"
                disabled={deleting}
                onClick={() => setDeleteTarget(null)}
              >
                Отмена
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
