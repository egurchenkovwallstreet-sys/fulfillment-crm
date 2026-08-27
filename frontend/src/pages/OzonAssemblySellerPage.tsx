import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { Link } from 'react-router-dom'
import {
  fetchAssemblySeller,
  scanOzonBarcode,
  shipOzonPosting,
  syncOzonAssembly,
  type AssemblyOrder,
  type AssemblySellerDetail,
} from '../api/assembly'
import { toggleSellerOzonWarehouse, type SellerOzonWarehouse } from '../api/sellers'
import './AssemblyPage.css'

const STAGES = [
  { key: 'new', label: 'Новые' },
  { key: 'confirm', label: 'На сборке' },
  { key: 'complete', label: 'В доставке' },
] as const

function stageCount(counts: Record<string, number> | undefined, key: string): number {
  if (key === 'confirm') return counts?.in_picking ?? 0
  if (key === 'complete') return counts?.in_delivery ?? 0
  return counts?.new ?? 0
}

export function OzonAssemblySellerPage({ sellerId }: { sellerId: number }) {
  const scanRef = useRef<HTMLInputElement>(null)
  const [data, setData] = useState<AssemblySellerDetail | null>(null)
  const [stage, setStage] = useState('new')
  const [loading, setLoading] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [barcode, setBarcode] = useState('')
  const [togglingId, setTogglingId] = useState<number | null>(null)
  const skipStageLoad = useRef(true)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setData(await fetchAssemblySeller(sellerId, stage))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка загрузки')
    } finally {
      setLoading(false)
    }
  }, [sellerId, stage])

  useEffect(() => {
    skipStageLoad.current = true
    let cancelled = false
    async function boot() {
      setSyncing(true)
      setError('')
      try {
        const payload = await syncOzonAssembly(sellerId, stage)
        if (!cancelled) setData(payload)
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Ошибка синхронизации Ozon')
          await load()
        }
      } finally {
        if (!cancelled) setSyncing(false)
      }
    }
    void boot()
    return () => {
      cancelled = true
    }
    // Первая загрузка селлера тянет склады и отправления из Ozon.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sellerId])

  useEffect(() => {
    if (skipStageLoad.current) {
      skipStageLoad.current = false
      return
    }
    void load()
  }, [load])

  useEffect(() => {
    scanRef.current?.focus()
  }, [stage, data?.orders.length])

  async function handleSync() {
    setSyncing(true)
    setError('')
    setSuccess('')
    try {
      const payload = await syncOzonAssembly(sellerId, stage)
      setData(payload)
      setSuccess('Отправления Ozon обновлены')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка синхронизации Ozon')
    } finally {
      setSyncing(false)
    }
  }

  async function handleScan(e?: FormEvent) {
    e?.preventDefault()
    const value = barcode.trim()
    if (!value) return
    setError('')
    setSuccess('')
    try {
      const result = await scanOzonBarcode(sellerId, value)
      setSuccess(result.message)
      setBarcode('')
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Баркод не найден')
    } finally {
      scanRef.current?.focus()
    }
  }

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') {
      e.preventDefault()
      void handleScan()
    }
  }

  async function handleShip(order: AssemblyOrder) {
    setError('')
    setSuccess('')
    try {
      const result = await shipOzonPosting(sellerId, order.id)
      setSuccess(result.message)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось передать к отгрузке')
    }
  }

  async function handleToggleWarehouse(warehouse: SellerOzonWarehouse) {
    setTogglingId(warehouse.id)
    try {
      await toggleSellerOzonWarehouse(sellerId, warehouse.id, !warehouse.is_enabled)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось переключить склад')
    } finally {
      setTogglingId(null)
    }
  }

  const warehouses = (data?.warehouses || []) as unknown as SellerOzonWarehouse[]
  const counts = data?.counts

  return (
    <>
      <header className="topbar">
        <div>
          <p>
            <Link to="/assembly">← Селлеры Ozon</Link>
          </p>
          <h1>{data?.seller.company_name || 'Сборка Ozon'}</h1>
          <p>Новые → скан баркода → на сборке → в доставку (ship Ozon)</p>
        </div>
        <button type="button" className="btn btn--primary" onClick={handleSync} disabled={syncing || loading}>
          {syncing ? 'Обновление…' : 'Обновить из Ozon'}
        </button>
      </header>

      {error && <div className="alert alert--error">{error}</div>}
      {success && <div className="alert alert--success">{success}</div>}

      {warehouses.length > 0 && (
        <section className="panel">
          <h2 className="section-title">Склады Ozon</h2>
          <div className="assembly-warehouses">
            {warehouses.map((wh) => (
              <label key={wh.id} className="assembly-warehouse">
                <input
                  type="checkbox"
                  checked={wh.is_enabled}
                  disabled={togglingId === wh.id}
                  onChange={() => void handleToggleWarehouse(wh)}
                />
                {wh.name || `Склад #${wh.ozon_warehouse_id}`}
                {wh.is_rfbs ? ' · rFBS' : ''}
              </label>
            ))}
          </div>
        </section>
      )}

      <nav className="assembly-pipeline">
        {STAGES.map((item) => (
          <button
            key={item.key}
            type="button"
            className={`assembly-stage${stage === item.key ? ' assembly-stage--active' : ''}`}
            onClick={() => setStage(item.key)}
          >
            <span className="assembly-stage__label">{item.label}</span>
            <span className="assembly-stage__count">{stageCount(counts, item.key)}</span>
          </button>
        ))}
      </nav>

      {stage === 'new' && (
        <form className="panel assembly-scan-panel" onSubmit={handleScan}>
          <label>
            Скан баркода (новые)
            <input
              ref={scanRef}
              className="assembly-scan-input"
              type="text"
              value={barcode}
              onChange={(e) => setBarcode(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Наведите сканер"
              autoComplete="off"
            />
          </label>
          <button type="submit" className="btn btn--primary">
            На сборку
          </button>
        </form>
      )}

      <section className="panel">
        {loading && !data && <p>Загрузка…</p>}
        <table className="assembly-table">
          <thead>
            <tr>
              <th>Отправление</th>
              <th>Ячейка</th>
              <th>Баркод</th>
              <th>Товар</th>
              <th>Статус Ozon</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {(data?.orders || []).length === 0 && !loading && (
              <tr>
                <td colSpan={6} className="assembly-table__empty">
                  Нет отправлений в этой вкладке. Нажмите «Обновить из Ozon».
                </td>
              </tr>
            )}
            {(data?.orders || []).map((order) => (
              <tr key={order.id}>
                <td>
                  <strong>{order.posting_number || order.id}</strong>
                </td>
                <td>{order.cell_number || '—'}</td>
                <td>{order.barcode}</td>
                <td>
                  {order.product_name || '—'}
                  {order.tech_size ? ` · ${order.tech_size}` : ''}
                </td>
                <td>{order.wb_status}</td>
                <td>
                  {stage === 'confirm' && (
                    <button
                      type="button"
                      className="btn btn--primary btn--small"
                      onClick={() => void handleShip(order)}
                      disabled={order.requires_marking && !order.marking_bound}
                    >
                      В доставку
                    </button>
                  )}
                  {order.requires_marking && !order.marking_bound && stage === 'confirm' && (
                    <span className="sellers-tag sellers-tag--warn">нужен ЧЗ</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  )
}
