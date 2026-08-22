import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  bindMarking,
  fetchAssemblySeller,
  replaceOrderItem,
  scanOrderBarcode,
  sendOrderToAssembly,
  sendAllOrdersToAssembly,
  sendOrderToDelivery,
  startAssembly,
  type AssemblyOrder,
  type AssemblySellerDetail,
  type PrintOrder,
} from '../api/assembly'
import { syncOrders } from '../api/orders'
import { syncSellerWarehouses, toggleSellerWarehouse } from '../api/sellers'
import { printPickList } from '../utils/pickListPrint'
import './AssemblyPage.css'

const STAGES = [
  { key: 'new', label: 'Новые', tone: 'red' },
  { key: 'confirm', label: 'На сборке', tone: 'orange' },
  { key: 'complete', label: 'В доставке', tone: 'blue' },
] as const

type ScanPhase = 'barcode' | 'marking'

function isWbNew(order: AssemblyOrder): boolean {
  const wb = (order.wb_supplier_status || '').trim()
  return wb === '' || wb === 'new'
}

function showAssemblyButton(order: AssemblyOrder, currentStage: string): boolean {
  if (currentStage === 'new') return isWbNew(order)
  return order.can_send_to_assembly ?? false
}

function showDeliveryButton(order: AssemblyOrder, currentStage: string): boolean {
  if (order.can_send_to_delivery) return true
  if (currentStage !== 'confirm') return false
  if ((order.wb_supplier_status || '').trim() !== 'confirm') return false
  if (order.status === 'label_printed') return true
  if (order.status === 'marked' && order.marking_bound) return true
  return false
}

export function AssemblySellerPage() {
  const { sellerId } = useParams<{ sellerId: string }>()
  const id = Number(sellerId)
  const scanRef = useRef<HTMLInputElement>(null)
  const markingRef = useRef<HTMLInputElement>(null)

  const [data, setData] = useState<AssemblySellerDetail | null>(null)
  const [stage, setStage] = useState('new')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [scanValue, setScanValue] = useState('')
  const [markingValue, setMarkingValue] = useState('')
  const [scanPhase, setScanPhase] = useState<ScanPhase>('barcode')
  const [pendingOrder, setPendingOrder] = useState<PrintOrder | null>(null)
  const [stickerPreview, setStickerPreview] = useState<string | null>(null)
  const [lastPrinted, setLastPrinted] = useState<AssemblyOrder | null>(null)

  const [syncing, setSyncing] = useState(true)

  const load = useCallback(async () => {
    if (!id) return
    setLoading(true)
    setError('')
    try {
      setData(await fetchAssemblySeller(id, stage || undefined))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка загрузки')
    } finally {
      setLoading(false)
    }
  }, [id, stage])

  useEffect(() => {
    setData(null)
  }, [id])

  useEffect(() => {
    if (!id) return
    let cancelled = false

    async function init() {
      setSyncing(true)
      setError('')
      try {
        await syncOrders(id)
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Ошибка синхронизации с WB')
        }
      } finally {
        if (!cancelled) {
          setSyncing(false)
        }
      }
    }

    init()
    return () => {
      cancelled = true
    }
  }, [id])

  useEffect(() => {
    if (!id || syncing) return
    load()
  }, [id, stage, load, syncing])

  useEffect(() => {
    if (scanPhase === 'marking') {
      markingRef.current?.focus()
    } else {
      scanRef.current?.focus()
    }
  }, [scanPhase])

  function resetScanFlow() {
    setScanPhase('barcode')
    setPendingOrder(null)
    setMarkingValue('')
    setScanValue('')
    scanRef.current?.focus()
  }

  function printSticker(base64: string) {
    const win = window.open('', '_blank', 'width=400,height=600')
    if (!win) return
    win.document.write(`
      <html><head><title>Стикер FBS</title></head>
      <body style="margin:0;text-align:center" onload="window.print();window.close()">
        <img src="data:image/png;base64,${base64}" style="max-width:100%" />
      </body></html>
    `)
    win.document.close()
  }

  function printSupplyBarcode(base64: string) {
    const win = window.open('', '_blank', 'width=400,height=400')
    if (!win) return
    win.document.write(`
      <html><head><title>QR поставки</title></head>
      <body style="margin:0;text-align:center" onload="window.print();window.close()">
        <img src="data:image/png;base64,${base64}" style="max-width:100%" />
      </body></html>
    `)
    win.document.close()
  }

  function finishPrint(order: PrintOrder) {
    setStickerPreview(order.sticker_file)
    setLastPrinted(order as unknown as AssemblyOrder)
    setSuccess(`Стикер заказа WB #${order.wb_order_id} отправлен на печать`)
    printSticker(order.sticker_file)
    resetScanFlow()
  }

  async function handleStartAssembly() {
    if (!id) return
    setError('')
    setSuccess('')
    setLoading(true)
    try {
      const result = await startAssembly(id)
      let msg = `Сборка начата: ${result.orders_count} заказов, стикеров ${result.stickers_fetched}`
      if (result.sticker_errors) {
        msg += `. Ошибка стикеров: ${result.sticker_errors}`
      }
      setSuccess(msg)
      await load()
      if (result.pick_list) {
        printPickList(result.pick_list)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка начала сборки')
    } finally {
      setLoading(false)
    }
  }

  function handlePrintPickList() {
    if (!data?.active_pick_list) return
    if (!printPickList(data.active_pick_list)) {
      setError('Не удалось открыть окно печати')
    }
  }

  async function handleSyncWarehouses() {
    if (!id) return
    setLoading(true)
    setError('')
    try {
      const result = await syncSellerWarehouses(id)
      setSuccess(`Склады WB обновлены: ${result.total} шт.`)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка загрузки складов WB')
    } finally {
      setLoading(false)
    }
  }

  async function handleToggleWarehouse(warehouseId: number, isEnabled: boolean) {
    if (!id) return
    setError('')
    try {
      await toggleSellerWarehouse(id, warehouseId, isEnabled)
      setSuccess(isEnabled ? 'Склад включён — заказы будут видны' : 'Склад выключен — заказы скрыты')
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка переключения склада')
    }
  }

  async function handleSendToAssembly(orderId: number) {
    if (!id) return
    setError('')
    setSuccess('')
    setLoading(true)
    try {
      const result = await sendOrderToAssembly(id, orderId)
      let msg = `Заказ WB #${result.order.wb_order_id} на сборке в WB`
      if (result.stickers_fetched) {
        msg += ', стикер загружен'
      }
      if (result.sticker_error) {
        msg += `. Ошибка стикера: ${result.sticker_error}`
      }
      setSuccess(msg)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка отправки на сборку')
    } finally {
      setLoading(false)
    }
  }

  async function handleSendAllToAssembly() {
    if (!id) return
    setError('')
    setSuccess('')
    setLoading(true)
    try {
      const result = await sendAllOrdersToAssembly(id)
      let msg = `На сборку отправлено: ${result.sent} из ${result.total}, стикеров ${result.stickers_fetched}`
      if (result.errors.length > 0) {
        msg += `. Ошибок: ${result.errors.length}`
      }
      setSuccess(msg)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка массовой отправки на сборку')
    } finally {
      setLoading(false)
    }
  }

  async function handleSendToDelivery(orderId: number) {
    if (!id) return
    setError('')
    setSuccess('')
    setLoading(true)
    try {
      const result = await sendOrderToDelivery(id, orderId)
      let msg = `Заказ WB #${result.order.wb_order_id} передан в доставку`
      if (result.supply_barcode_file) {
        printSupplyBarcode(result.supply_barcode_file)
        msg += ', QR поставки отправлен на печать'
      }
      setSuccess(msg)
      setLastPrinted(null)
      setStage('complete')
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка отправки в доставку')
    } finally {
      setLoading(false)
    }
  }

  async function handleSync() {
    if (!id) return
    setLoading(true)
    setError('')
    try {
      await syncOrders(id)
      await load()
      setSuccess('Заказы обновлены из WB')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка синхронизации')
    } finally {
      setLoading(false)
    }
  }

  async function handleBarcodeSubmit(e?: FormEvent) {
    e?.preventDefault()
    if (!id || !scanValue.trim()) return
    setError('')
    setSuccess('')
    setLoading(true)
    try {
      const result = await scanOrderBarcode(id, scanValue.trim())
      if (result.action === 'await_marking') {
        setPendingOrder(result.order)
        setScanPhase('marking')
        setScanValue('')
        setSuccess(result.message || 'Отсканируйте код Честного знака (DataMatrix)')
      } else {
        finishPrint(result.order)
      }
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка сканирования баркода')
    } finally {
      setLoading(false)
      if (scanPhase === 'barcode') {
        scanRef.current?.focus()
      }
    }
  }

  async function handleMarkingSubmit(e?: FormEvent) {
    e?.preventDefault()
    if (!id || !pendingOrder || !markingValue.trim()) return
    setError('')
    setSuccess('')
    setLoading(true)
    try {
      const result = await bindMarking(id, pendingOrder.id, markingValue.trim())
      finishPrint(result.order)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка привязки Честного знака')
      markingRef.current?.focus()
    } finally {
      setLoading(false)
    }
  }

  async function handleReplaceOrder() {
    if (!id || !pendingOrder) return
    setError('')
    setSuccess('')
    setLoading(true)
    try {
      const result = await replaceOrderItem(id, pendingOrder.id)
      setSuccess(result.message)
      resetScanFlow()
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка замены товара')
    } finally {
      setLoading(false)
    }
  }

  function handleScanKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') {
      e.preventDefault()
      handleBarcodeSubmit()
    }
  }

  function handleMarkingKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') {
      e.preventDefault()
      handleMarkingSubmit()
    }
  }

  if (!data) {
    return (
      <div className="loading-screen">
        <div className="loading-screen__spinner" />
        <p>{syncing ? 'Синхронизация с WB…' : 'Загрузка…'}</p>
      </div>
    )
  }

  const counts = data.counts

  function stageCount(key: string): number {
    if (key === 'confirm') return counts.in_picking ?? 0
    if (key === 'complete') return counts.in_delivery ?? 0
    return counts.new ?? 0
  }

  const newTabOrdersCount =
    stage === 'new'
      ? data.orders.filter((order) => isWbNew(order)).length
      : 0
  const bulkAssemblyCount = data.assembly_eligible ?? newTabOrdersCount

  return (
    <>
      <header className="topbar">
        <div>
          <p className="assembly-breadcrumb">
            <Link to="/assembly">Сборка FBS</Link> / {data.seller.company_name}
          </p>
          <h1>{data.seller.company_name}</h1>
          <p>Кабинет сборки · поставок в работе: {data.supplies_forming}</p>
        </div>
        <div className="topbar__actions">
          <button type="button" className="btn btn--secondary" onClick={handleSync} disabled={loading || syncing}>
            Обновить из WB
          </button>
          {(counts.new ?? 0) > 0 && (
            <button type="button" className="btn btn--secondary" onClick={handleStartAssembly} disabled={loading}>
              Лист подбора ({counts.new})
            </button>
          )}
          {data.active_pick_list && (
            <button type="button" className="btn btn--secondary" onClick={handlePrintPickList} disabled={loading}>
              Печать листа
            </button>
          )}
          {stage === 'new' && bulkAssemblyCount > 0 && (
            <button type="button" className="btn btn--primary" onClick={handleSendAllToAssembly} disabled={loading}>
              Все на сборку ({bulkAssemblyCount})
            </button>
          )}
        </div>
      </header>

      {error && <div className="alert alert--error">{error}</div>}
      {success && <div className="alert alert--success">{success}</div>}

      <section className="assembly-pipeline">
        {STAGES.map((s) => (
          <button
            key={s.key}
            type="button"
            className={`assembly-stage assembly-stage--${s.tone}${stage === s.key ? ' assembly-stage--active' : ''}`}
            onClick={() => setStage(s.key)}
          >
            <span className="assembly-stage__count">{stageCount(s.key)}</span>
            <span className="assembly-stage__label">{s.label}</span>
          </button>
        ))}
      </section>

      <section className="panel assembly-warehouses">
        <div className="assembly-warehouses__header">
          <h2 className="section-title">Точки отгрузки WB</h2>
          <button
            type="button"
            className="btn btn--secondary btn--small"
            onClick={handleSyncWarehouses}
            disabled={loading}
          >
            Загрузить из WB
          </button>
        </div>
        <p className="assembly-warehouses__hint">
          Включите только те склады, которые обслуживает ваш фулфилмент. Выключенные склады полностью скрыты.
        </p>
        {data.warehouses.length === 0 ? (
          <p className="assembly-warehouses__empty">Нажмите «Загрузить из WB», чтобы получить список складов</p>
        ) : (
          <ul className="assembly-warehouses__list">
            {data.warehouses.map((wh) => (
              <li key={wh.id} className={wh.is_enabled ? '' : 'assembly-warehouses__item--off'}>
                <label className="assembly-warehouses__toggle">
                  <input
                    type="checkbox"
                    checked={wh.is_enabled}
                    onChange={(e) => handleToggleWarehouse(wh.id, e.target.checked)}
                    disabled={loading}
                  />
                  <span className="assembly-warehouses__name">
                    {wh.name || `Склад #${wh.wb_warehouse_id}`}
                  </span>
                </label>
                {wh.address && <span className="assembly-warehouses__addr">{wh.address}</span>}
              </li>
            ))}
          </ul>
        )}
      </section>

      <div className="assembly-grid">
        <section className="panel">
          <h2 className="section-title">
            Заказы ({stageCount(stage)})
          </h2>
          <table className="assembly-table">
            <thead>
              <tr>
                <th>WB ID</th>
                <th>Баркод</th>
                <th>Ячейка</th>
                <th>ЧЗ</th>
                <th>Статус</th>
                <th>Стикер</th>
                <th>Действие</th>
              </tr>
            </thead>
            <tbody>
              {data.orders.map((order) => (
                <tr key={order.id}>
                  <td>{order.wb_order_id}</td>
                  <td><code>{order.barcode}</code></td>
                  <td>{order.cell_number || '—'}</td>
                  <td>
                    {order.requires_marking ? (
                      order.marking_bound ? (
                        <span className="marking-badge marking-badge--ok">✓</span>
                      ) : (
                        <span className="marking-badge marking-badge--required">ЧЗ</span>
                      )
                    ) : (
                      '—'
                    )}
                  </td>
                  <td>{order.wb_stage_display || order.status_display}</td>
                  <td>{order.has_sticker ? '✓' : '—'}</td>
                  <td className="assembly-table__actions">
                    {showAssemblyButton(order, stage) && (
                      <button
                        type="button"
                        className="btn btn--small btn--primary"
                        onClick={() => handleSendToAssembly(order.id)}
                        disabled={loading}
                      >
                        На сборку
                      </button>
                    )}
                    {showDeliveryButton(order, stage) && (
                      <button
                        type="button"
                        className="btn btn--small btn--secondary"
                        onClick={() => handleSendToDelivery(order.id)}
                        disabled={loading}
                      >
                        В доставку
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <div className="assembly-side">
          {data.active_pick_list && (
            <section className="panel">
              <div className="assembly-picklist-head">
                <h2 className="section-title">Лист подбора #{data.active_pick_list.id}</h2>
                <button
                  type="button"
                  className="btn btn--secondary btn--small"
                  onClick={handlePrintPickList}
                  disabled={loading}
                >
                  Печать PDF
                </button>
              </div>
              <table className="assembly-table pick-list-table">
                <thead>
                  <tr>
                    <th>Ячейка</th>
                    <th>Баркод</th>
                    <th>Кол-во</th>
                  </tr>
                </thead>
                <tbody>
                  {data.active_pick_list.items.map((item) => (
                    <tr key={item.id}>
                      <td><strong>{item.cell_number}</strong></td>
                      <td><code>{item.barcode}</code></td>
                      <td>{item.quantity} шт.</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}

          <section className="panel assembly-scan-panel">
            {scanPhase === 'barcode' ? (
              <>
                <h2 className="section-title">Сборка: скан баркода</h2>
                <p className="assembly-scan-hint">
                  1) «На сборку» — по одному заказу в WB. 2) Скан баркода → печать стикера.
                  3) «В доставку» — после печати (и ЧЗ, если нужен).
                </p>
                <form onSubmit={handleBarcodeSubmit}>
                  <input
                    ref={scanRef}
                    type="text"
                    className="assembly-scan-input"
                    value={scanValue}
                    onChange={(e) => setScanValue(e.target.value)}
                    onKeyDown={handleScanKeyDown}
                    placeholder="Баркод заказа..."
                    autoComplete="off"
                  />
                </form>
              </>
            ) : (
              <>
                <h2 className="section-title assembly-scan-panel--marking">
                  Требуется Честный знак
                </h2>
                {pendingOrder && (
                  <div className="assembly-pending-order">
                    <p>Заказ WB <strong>#{pendingOrder.wb_order_id}</strong></p>
                    <p>Баркод: <code>{pendingOrder.barcode}</code></p>
                  </div>
                )}
                <p className="assembly-scan-hint">
                  Отсканируйте DataMatrix с упаковки. После привязки в WB стикер отправится на печать автоматически.
                </p>
                <form onSubmit={handleMarkingSubmit}>
                  <input
                    ref={markingRef}
                    type="text"
                    className="assembly-scan-input assembly-scan-input--marking"
                    value={markingValue}
                    onChange={(e) => setMarkingValue(e.target.value)}
                    onKeyDown={handleMarkingKeyDown}
                    placeholder="Код Честного знака (DataMatrix)..."
                    autoComplete="off"
                  />
                </form>
                <div className="assembly-scan-actions">
                  <button
                    type="button"
                    className="btn btn--secondary"
                    onClick={handleReplaceOrder}
                    disabled={loading}
                  >
                    Заменить товар
                  </button>
                  <button
                    type="button"
                    className="btn btn--secondary"
                    onClick={resetScanFlow}
                    disabled={loading}
                  >
                    Отмена
                  </button>
                </div>
              </>
            )}

            {lastPrinted && scanPhase === 'barcode' && (
              <div className="assembly-last-print">
                <p>
                  Последний: WB #{lastPrinted.wb_order_id} · {lastPrinted.barcode}
                </p>
                {lastPrinted && (lastPrinted.can_send_to_delivery || showDeliveryButton(lastPrinted, 'confirm')) && (
                  <button
                    type="button"
                    className="btn btn--small btn--secondary"
                    onClick={() => handleSendToDelivery(lastPrinted.id)}
                    disabled={loading}
                  >
                    В доставку
                  </button>
                )}
              </div>
            )}
            {stickerPreview && scanPhase === 'barcode' && (
              <div className="assembly-sticker-preview">
                <img src={`data:image/png;base64,${stickerPreview}`} alt="Стикер FBS" />
                <button
                  type="button"
                  className="btn btn--secondary"
                  onClick={() => printSticker(stickerPreview)}
                >
                  Печать ещё раз
                </button>
              </div>
            )}
          </section>
        </div>
      </div>
    </>
  )
}
