import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  fetchAssemblySeller,
  scanPrintSticker,
  startAssembly,
  type AssemblyOrder,
  type AssemblySellerDetail,
} from '../api/assembly'
import { syncOrders } from '../api/orders'
import './AssemblyPage.css'

const STAGES = [
  { key: '', label: 'Все активные' },
  { key: 'new', label: 'Новые' },
  { key: 'in_picking', label: 'На сборке' },
  { key: 'label_printed', label: 'Этикетка' },
  { key: 'marked', label: 'ЧЗ' },
  { key: 'in_supply', label: 'В поставке' },
]

export function AssemblySellerPage() {
  const { sellerId } = useParams<{ sellerId: string }>()
  const id = Number(sellerId)
  const scanRef = useRef<HTMLInputElement>(null)

  const [data, setData] = useState<AssemblySellerDetail | null>(null)
  const [stage, setStage] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [scanValue, setScanValue] = useState('')
  const [stickerPreview, setStickerPreview] = useState<string | null>(null)
  const [lastPrinted, setLastPrinted] = useState<AssemblyOrder | null>(null)

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
    load()
  }, [load])

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
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка начала сборки')
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

  async function handleScanSubmit(e?: FormEvent) {
    e?.preventDefault()
    if (!id || !scanValue.trim()) return
    setError('')
    setSuccess('')
    setLoading(true)
    try {
      const result = await scanPrintSticker(id, scanValue.trim())
      setStickerPreview(result.order.sticker_file)
      setLastPrinted(result.order as unknown as AssemblyOrder)
      setSuccess(`Стикер заказа WB #${result.order.wb_order_id} готов к печати`)
      setScanValue('')
      await load()
      printSticker(result.order.sticker_file)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка сканирования')
    } finally {
      setLoading(false)
      scanRef.current?.focus()
    }
  }

  function handleScanKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') {
      e.preventDefault()
      handleScanSubmit()
    }
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

  if (!data) {
    return <div className="loading-screen"><div className="loading-screen__spinner" /></div>
  }

  const counts = data.counts
  const totalActive = ['new', 'in_picking', 'assembled', 'label_printed', 'marked', 'in_supply']
    .reduce((sum, key) => sum + (counts[key] ?? 0), 0)

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
          <button type="button" className="btn btn--secondary" onClick={handleSync} disabled={loading}>
            Обновить из WB
          </button>
          {(counts.new ?? 0) > 0 && (
            <button type="button" className="btn btn--primary" onClick={handleStartAssembly} disabled={loading}>
              Начать сборку ({counts.new})
            </button>
          )}
        </div>
      </header>

      {error && <div className="alert alert--error">{error}</div>}
      {success && <div className="alert alert--success">{success}</div>}

      <section className="assembly-pipeline">
        {STAGES.map((s) => (
          <button
            key={s.key || 'all'}
            type="button"
            className={`assembly-stage${stage === s.key ? ' assembly-stage--active' : ''}`}
            onClick={() => setStage(s.key)}
          >
            <span className="assembly-stage__count">{s.key ? (counts[s.key] ?? 0) : totalActive}</span>
            <span className="assembly-stage__label">{s.label}</span>
          </button>
        ))}
      </section>

      <div className="assembly-grid">
        <section className="panel">
          <h2 className="section-title">Заказы ({data.orders.length})</h2>
          <table className="assembly-table">
            <thead>
              <tr>
                <th>WB ID</th>
                <th>Баркод</th>
                <th>Ячейка</th>
                <th>Статус</th>
                <th>Стикер</th>
              </tr>
            </thead>
            <tbody>
              {data.orders.map((order) => (
                <tr key={order.id}>
                  <td>{order.wb_order_id}</td>
                  <td><code>{order.barcode}</code></td>
                  <td>{order.cell_number || '—'}</td>
                  <td>{order.status_display}</td>
                  <td>{order.has_sticker ? '✓' : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <div className="assembly-side">
          {data.active_pick_list && (
            <section className="panel">
              <h2 className="section-title">Лист подбора #{data.active_pick_list.id}</h2>
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
            <h2 className="section-title">Печать по скану</h2>
            <p className="assembly-scan-hint">Отсканируйте баркод заказа для печати стикера FBS</p>
            <form onSubmit={handleScanSubmit}>
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
            {lastPrinted && (
              <p className="assembly-last-print">
                Последний: WB #{lastPrinted.wb_order_id} · {lastPrinted.barcode}
              </p>
            )}
            {stickerPreview && (
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
