import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { Link } from 'react-router-dom'
import {
  bindOzonMarking,
  fetchAssemblySeller,
  fetchOzonLabel,
  fetchOzonLabelsBulk,
  formOzonAct,
  scanOzonBarcode,
  shipOzonPosting,
  syncOzonAssembly,
  type AssemblyOrder,
  type AssemblySellerDetail,
} from '../api/assembly'
import { toggleSellerOzonWarehouse, type SellerOzonWarehouse } from '../api/sellers'
import { ApiError } from '../api/client'
import { openPdfBase64 } from '../utils/browserPrint'
import { printSupplySticker } from '../utils/printService'
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
  const [busyId, setBusyId] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [barcode, setBarcode] = useState('')
  const [pendingMarking, setPendingMarking] = useState<AssemblyOrder | null>(null)
  const [lastCarriageId, setLastCarriageId] = useState<number | null>(null)
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
  }, [stage, data?.orders.length, pendingMarking?.id])

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
      if (stage === 'confirm' || pendingMarking) {
        const target = pendingMarking || data?.orders.find((item) => item.requires_marking && !item.marking_bound)
        if (!target) {
          setError('Сначала отсканируйте баркод во вкладке «Новые» или нажмите «Скан ЧЗ» в строке')
          return
        }
        const result = await bindOzonMarking(sellerId, target.id, value)
        setSuccess(result.message)
        setBarcode('')
        if (result.action === 'bound') {
          setPendingMarking(null)
        } else {
          setPendingMarking(result.posting)
        }
        await load()
        return
      }
      const result = await scanOzonBarcode(sellerId, value)
      setSuccess(result.message)
      setBarcode('')
      if (result.action === 'await_marking') {
        setPendingMarking(result.posting)
        setStage('confirm')
      }
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Скан не принят')
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
    setBusyId(order.id)
    try {
      const result = await shipOzonPosting(sellerId, order.id)
      setSuccess(result.message)
      setStage('complete')
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось передать к отгрузке')
    } finally {
      setBusyId(null)
    }
  }

  async function handleLabel(order: AssemblyOrder) {
    setError('')
    setSuccess('')
    setBusyId(order.id)
    try {
      const result = await fetchOzonLabel(sellerId, order.id)
      openPdfBase64(result.pdf_base64, result.filename)
      setSuccess(`Этикетка ${order.posting_number} открыта. Напечатайте из окна PDF.`)
    } catch (err) {
      const code = err instanceof ApiError ? err.code : ''
      if (code === 'not_ready') {
        setError('Этикетка ещё готовится. Подождите около минуты после «В доставку» и нажмите ещё раз.')
      } else {
        setError(err instanceof Error ? err.message : 'Не удалось получить этикетку')
      }
    } finally {
      setBusyId(null)
    }
  }

  async function handleLabelsAll() {
    const ids = (data?.orders || []).filter((item) => item.can_print_label).map((item) => item.id)
    if (ids.length < 1) return
    setError('')
    setSuccess('')
    setBusyId(-1)
    try {
      const result = await fetchOzonLabelsBulk(sellerId, ids.slice(0, 20))
      openPdfBase64(result.pdf_base64, result.filename)
      setSuccess(`Открыт PDF с ${result.count ?? ids.length} этикетками`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось получить этикетки')
    } finally {
      setBusyId(null)
    }
  }

  async function handleAct(carriageId?: number) {
    setError('')
    setSuccess('')
    setBusyId(-2)
    try {
      const result = await formOzonAct(sellerId, carriageId)
      const acts = result.acts?.length ? result.acts : [result]
      for (const act of acts) {
        if (act.carriage_id) setLastCarriageId(act.carriage_id)
        if (act.barcode_file) {
          if (act.barcode_file.includes('application/pdf') || act.barcode_file.startsWith('JVBERi0')) {
            openPdfBase64(act.barcode_file, act.filename || 'ozon-barcode.pdf')
          } else {
            await printSupplySticker(act.barcode_file)
          }
        }
        if (act.pdf_base64) {
          openPdfBase64(act.pdf_base64, act.filename || 'ozon-act.pdf')
        }
      }
      setSuccess(result.message || 'Акт сформирован')
      if (acts.some((item) => item.warning)) {
        setError(acts.map((item) => item.warning).filter(Boolean).join(' '))
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось сформировать акт')
    } finally {
      setBusyId(null)
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
  const scanOnPicking = stage === 'confirm'
  const scanLabel = scanOnPicking
    ? pendingMarking
      ? `Честный знак для ${pendingMarking.posting_number}`
      : 'Честный знак (DataMatrix)'
    : 'Скан баркода (новые)'

  return (
    <>
      <header className="topbar">
        <div>
          <p>
            <Link to="/assembly">← Селлеры Ozon</Link>
          </p>
          <h1>{data?.seller.company_name || 'Сборка Ozon'}</h1>
          <p>Новые → скан → ЧЗ (если нужен) → в доставку → этикетка PDF → акт/ШК</p>
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

      {(stage === 'new' || stage === 'confirm') && (
        <form className="panel assembly-scan-panel" onSubmit={handleScan}>
          <label>
            {scanLabel}
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
            {scanOnPicking ? 'Привязать ЧЗ' : 'На сборку'}
          </button>
        </form>
      )}

      {stage === 'complete' && (
        <section className="panel assembly-scan-panel">
          <button
            type="button"
            className="btn btn--primary"
            onClick={() => void handleAct()}
            disabled={busyId === -2 || (data?.orders || []).length === 0}
          >
            {busyId === -2 ? 'Формирование…' : 'Сформировать акт и ШК'}
          </button>
          <button
            type="button"
            className="btn btn--secondary"
            onClick={() => void handleLabelsAll()}
            disabled={busyId === -1 || (data?.orders || []).length === 0}
          >
            Печать этикеток (до 20)
          </button>
          {lastCarriageId ? (
            <button
              type="button"
              className="btn btn--ghost"
              onClick={() => void handleAct(lastCarriageId)}
              disabled={busyId === -2}
            >
              Повторить документы
            </button>
          ) : null}
          <p className="whub-hint">
            Этикетку запрашивайте через минуту после «В доставку». Акт и ШК — для сдачи в пункт Ozon.
          </p>
        </section>
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
                  {order.quantity && order.quantity > 1 ? ` · ${order.quantity} шт.` : ''}
                </td>
                <td>{order.wb_status}</td>
                <td className="assembly-table__actions">
                  {stage === 'confirm' && order.requires_marking && !order.marking_bound && (
                    <button
                      type="button"
                      className="btn btn--secondary btn--small"
                      onClick={() => {
                        setPendingMarking(order)
                        scanRef.current?.focus()
                      }}
                    >
                      Скан ЧЗ
                      {order.marking_needed_count
                        ? ` ${order.marking_bound_count ?? 0}/${order.marking_needed_count}`
                        : ''}
                    </button>
                  )}
                  {stage === 'confirm' && (
                    <button
                      type="button"
                      className="btn btn--primary btn--small"
                      onClick={() => void handleShip(order)}
                      disabled={busyId === order.id || (order.requires_marking && !order.marking_bound)}
                    >
                      В доставку
                    </button>
                  )}
                  {order.requires_marking && !order.marking_bound && stage === 'confirm' && (
                    <span className="sellers-tag sellers-tag--warn">нужен ЧЗ</span>
                  )}
                  {stage === 'complete' && (
                    <button
                      type="button"
                      className="btn btn--secondary btn--small"
                      onClick={() => void handleLabel(order)}
                      disabled={busyId === order.id}
                    >
                      Этикетка
                    </button>
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
