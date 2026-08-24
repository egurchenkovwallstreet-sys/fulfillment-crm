import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchAssemblySellers } from '../api/assembly'
import {
  deliverSuppliesBulk,
  deliverSupply,
  fetchSupplies,
  fetchSupplyBarcode,
  type SupplyItem,
} from '../api/supplies'
import { printSupplySticker } from '../utils/printService'
import './AssemblyPage.css'
import './SuppliesPage.css'

type StatusFilter = '' | 'forming' | 'ready' | 'confirmed'

const STATUS_TABS: { value: StatusFilter; label: string }[] = [
  { value: '', label: 'Активные' },
  { value: 'forming', label: 'Формируются' },
  { value: 'ready', label: 'Готовы' },
  { value: 'confirmed', label: 'В доставке' },
]

function statusClass(status: string) {
  return `supply-status supply-status--${status}`
}

export function SuppliesPage() {
  const [sellers, setSellers] = useState<{ id: number; company_name: string }[]>([])
  const [sellerId, setSellerId] = useState<number | null>(null)
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('')
  const [supplies, setSupplies] = useState<SupplyItem[]>([])
  const [syncMessage, setSyncMessage] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [busySupplyId, setBusySupplyId] = useState<number | null>(null)

  useEffect(() => {
    fetchAssemblySellers()
      .then((items) => {
        setSellers(items)
        if (items.length > 0) {
          setSellerId(items[0].id)
        }
      })
      .catch((err) => setError(err instanceof Error ? err.message : 'Ошибка загрузки селлеров'))
  }, [])

  const load = useCallback(async () => {
    if (!sellerId) return
    setLoading(true)
    setError('')
    try {
      const result = await fetchSupplies(sellerId, {
        status: statusFilter || undefined,
      })
      setSupplies(result.supplies)
      const sync = result.sync
      setSyncMessage(
        `WB: поставок ${sync.wb_supplies_total}, в CRM ${result.supplies.length}. `
        + `Списано: ${sync.stock_deducted}${sync.stock_errors ? `, ошибок списания: ${sync.stock_errors}` : ''}`,
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка загрузки поставок')
    } finally {
      setLoading(false)
    }
  }, [sellerId, statusFilter])

  useEffect(() => {
    load()
  }, [load])

  const readyCount = useMemo(
    () => supplies.filter((s) => s.can_deliver).length,
    [supplies],
  )

  async function handleDeliver(supply: SupplyItem) {
    if (!window.confirm(`Передать поставку ${supply.wb_supply_id || supply.id} в доставку WB?`)) {
      return
    }
    setBusySupplyId(supply.id)
    setError('')
    try {
      const result = await deliverSupply(supply.id)
      if (result.supply_barcode_file) {
        await printSupplySticker(result.supply_barcode_file)
      }
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка передачи в доставку')
    } finally {
      setBusySupplyId(null)
    }
  }

  async function handleBulkDeliver() {
    if (!sellerId || readyCount === 0) return
    if (!window.confirm(`Передать в доставку ${readyCount} готовых поставок?`)) {
      return
    }
    setLoading(true)
    setError('')
    try {
      const result = await deliverSuppliesBulk(sellerId)
      for (const file of result.supply_barcode_files) {
        await printSupplySticker(file)
      }
      if (result.errors.length > 0) {
        setError(`Передано ${result.delivered}, ошибок: ${result.errors.length}`)
      }
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка массовой передачи')
    } finally {
      setLoading(false)
    }
  }

  async function handleReprintBarcode(supply: SupplyItem) {
    setBusySupplyId(supply.id)
    setError('')
    try {
      const result = await fetchSupplyBarcode(supply.id)
      if (result.supply_barcode_file) {
        await printSupplySticker(result.supply_barcode_file)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка печати ШК')
    } finally {
      setBusySupplyId(null)
    }
  }

  return (
    <>
      <header className="topbar">
        <div>
          <h1>Поставки WB</h1>
          <p>Список поставок, статусы, печать ШК и передача в доставку</p>
        </div>
        <div className="topbar__actions">
          {readyCount > 0 && (
            <button type="button" className="btn btn--primary" onClick={handleBulkDeliver} disabled={loading}>
              В доставку ({readyCount})
            </button>
          )}
          <button type="button" className="btn" onClick={load} disabled={loading || !sellerId}>
            {loading ? 'Обновление…' : 'Обновить'}
          </button>
        </div>
      </header>

      <div className="supplies-toolbar">
        <label>
          Селлер
          <select
            value={sellerId ?? ''}
            onChange={(e) => setSellerId(Number(e.target.value))}
          >
            {sellers.map((s) => (
              <option key={s.id} value={s.id}>
                {s.company_name}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="supplies-tabs">
        {STATUS_TABS.map((tab) => (
          <button
            key={tab.value || 'all'}
            type="button"
            className={statusFilter === tab.value ? 'supplies-tabs__btn--active' : ''}
            onClick={() => setStatusFilter(tab.value)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {syncMessage && <p className="supplies-sync-msg">{syncMessage}</p>}
      {error && <p className="form-error">{error}</p>}

      <div className="card assembly-sellers">
        <table className="assembly-table">
          <thead>
            <tr>
              <th>ID WB</th>
              <th>Статус</th>
              <th>Заказы</th>
              <th>ШК</th>
              <th>Остатки</th>
              <th>Создана</th>
              <th>Действия</th>
            </tr>
          </thead>
          <tbody>
            {supplies.length === 0 && (
              <tr>
                <td colSpan={7} className="assembly-table__empty">
                  {loading ? 'Загрузка…' : 'Нет поставок для выбранного фильтра'}
                </td>
              </tr>
            )}
            {supplies.map((supply) => (
              <tr key={supply.id}>
                <td>
                  <code>{supply.wb_supply_id || '—'}</code>
                </td>
                <td>
                  <span className={statusClass(supply.status)}>{supply.status_display}</span>
                </td>
                <td>
                  <button
                    type="button"
                    className="supplies-expand-btn"
                    onClick={() => setExpandedId(expandedId === supply.id ? null : supply.id)}
                  >
                    {supply.orders_count} шт.
                  </button>
                  {expandedId === supply.id && supply.orders.length > 0 && (
                    <ul className="supplies-orders">
                      {supply.orders.map((order) => (
                        <li key={order.id}>
                          #{order.wb_order_id} · {order.barcode}
                          {order.cell_number ? ` · яч. ${order.cell_number}` : ''}
                          {order.block_reason ? ` — ${order.block_reason}` : ''}
                        </li>
                      ))}
                    </ul>
                  )}
                </td>
                <td>
                  <span className={supply.supply_barcode_printed ? 'supply-flag supply-flag--ok' : 'supply-flag supply-flag--no'}>
                    {supply.supply_barcode_printed ? 'Да' : 'Нет'}
                  </span>
                </td>
                <td>
                  <span className={supply.stock_deducted ? 'supply-flag supply-flag--ok' : 'supply-flag supply-flag--no'}>
                    {supply.stock_deducted ? 'Списано' : 'Нет'}
                  </span>
                </td>
                <td>{new Date(supply.created_at).toLocaleString('ru-RU')}</td>
                <td className="assembly-table__actions">
                  {supply.can_deliver && (
                    <button
                      type="button"
                      className="btn btn--primary btn--sm"
                      disabled={busySupplyId === supply.id}
                      onClick={() => handleDeliver(supply)}
                    >
                      В доставку
                    </button>
                  )}
                  {supply.status === 'confirmed' && (
                    <button
                      type="button"
                      className="btn btn--sm"
                      disabled={busySupplyId === supply.id}
                      onClick={() => handleReprintBarcode(supply)}
                    >
                      ШК
                    </button>
                  )}
                  <Link className="btn btn--ghost btn--sm" to={`/assembly/${supply.seller}`}>
                    Сборка
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}
