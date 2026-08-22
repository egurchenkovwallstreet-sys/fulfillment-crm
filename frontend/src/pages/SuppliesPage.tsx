import { useCallback, useEffect, useState } from 'react'
import {
  deliverSuppliesBulk,
  deliverSupply,
  fetchSupplies,
  fetchSupplyBarcode,
  type Supply,
  type SupplyStatus,
} from '../api/supplies'
import { fetchSellers, type Seller } from '../api/warehouse'
import { printSupplySticker } from '../utils/browserPrint'
import './SuppliesPage.css'

type TabKey = 'active' | 'forming' | 'ready' | 'confirmed'

const TAB_LABELS: Record<TabKey, string> = {
  active: 'Все активные',
  forming: 'Формируются',
  ready: 'Готовы',
  confirmed: 'В доставке',
}

function statusClass(status: SupplyStatus): string {
  if (status === 'ready') return 'supplies-status supplies-status--ready'
  if (status === 'confirmed') return 'supplies-status supplies-status--confirmed'
  return 'supplies-status supplies-status--forming'
}

export function SuppliesPage() {
  const [sellers, setSellers] = useState<Seller[]>([])
  const [sellerId, setSellerId] = useState<number | ''>('')
  const [tab, setTab] = useState<TabKey>('active')
  const [supplies, setSupplies] = useState<Supply[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  useEffect(() => {
    fetchSellers()
      .then((data) => {
        setSellers(data)
        if (data.length === 1) setSellerId(data[0].id)
      })
      .catch((err) => setError(err instanceof Error ? err.message : 'Ошибка загрузки'))
  }, [])

  const loadSupplies = useCallback(async () => {
    if (!sellerId) {
      setSupplies([])
      return
    }
    setLoading(true)
    setError('')
    try {
      const statusFilter: SupplyStatus | '' =
        tab === 'forming' ? 'forming'
        : tab === 'ready' ? 'ready'
        : tab === 'confirmed' ? 'confirmed'
        : ''
      const data = await fetchSupplies(Number(sellerId), statusFilter)
      setSupplies(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка загрузки поставок')
    } finally {
      setLoading(false)
    }
  }, [sellerId, tab])

  useEffect(() => {
    loadSupplies()
  }, [loadSupplies])

  function printBarcodes(files: string[]) {
    for (const file of files) {
      if (file) printSupplySticker(file)
    }
  }

  async function handleDeliver(supplyId: number) {
    setLoading(true)
    setError('')
    setSuccess('')
    try {
      const result = await deliverSupply(supplyId)
      setSuccess(result.message)
      if (result.supply_barcode_file) {
        printSupplySticker(result.supply_barcode_file)
        setSuccess((prev) => `${prev}. QR поставки отправлен на печать`)
      }
      await loadSupplies()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка передачи в доставку')
    } finally {
      setLoading(false)
    }
  }

  async function handleBulkDeliver() {
    if (!sellerId) return
    const readyIds = supplies.filter((s) => s.can_deliver).map((s) => s.id)
    if (readyIds.length === 0) {
      setError('Нет готовых поставок для передачи в доставку')
      return
    }
    setLoading(true)
    setError('')
    setSuccess('')
    try {
      const result = await deliverSuppliesBulk(Number(sellerId), readyIds)
      setSuccess(result.message)
      if (result.supply_barcode_files?.length) {
        printBarcodes(result.supply_barcode_files)
        setSuccess((prev) => `${prev}. QR отправлены на печать`)
      }
      await loadSupplies()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка массовой передачи')
    } finally {
      setLoading(false)
    }
  }

  async function handleReprintBarcode(supplyId: number) {
    setError('')
    try {
      const result = await fetchSupplyBarcode(supplyId)
      printSupplySticker(result.supply_barcode_file)
      setSuccess(`ШК поставки ${result.wb_supply_id} отправлен на печать`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка печати ШК')
    }
  }

  const readyCount = supplies.filter((s) => s.can_deliver).length

  return (
    <>
      <header className="topbar">
        <div>
          <h1>Поставки FBS</h1>
          <p>Контроль готовности · блокировка без ЧЗ · печать QR поставки 58×40</p>
        </div>
      </header>

      {error && <div className="alert alert--error">{error}</div>}
      {success && <div className="alert alert--success">{success}</div>}

      <section className="card">
        <div className="supplies-toolbar">
          <label className="supplies-field">
            Селлер
            <select
              value={sellerId}
              onChange={(e) => setSellerId(e.target.value ? Number(e.target.value) : '')}
            >
              <option value="">— выберите селлера —</option>
              {sellers.map((s) => (
                <option key={s.id} value={s.id}>{s.company_name}</option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="btn btn--secondary"
            onClick={() => loadSupplies()}
            disabled={!sellerId || loading}
          >
            Обновить
          </button>
          {readyCount > 0 && (
            <button
              type="button"
              className="btn btn--primary"
              onClick={handleBulkDeliver}
              disabled={loading}
            >
              Все готовые в доставку ({readyCount})
            </button>
          )}
        </div>

        <div className="supplies-tabs">
          {(Object.keys(TAB_LABELS) as TabKey[]).map((key) => (
            <button
              key={key}
              type="button"
              className={`supplies-tab${tab === key ? ' supplies-tab--active' : ''}`}
              onClick={() => setTab(key)}
            >
              {TAB_LABELS[key]}
            </button>
          ))}
        </div>

        {!sellerId ? (
          <p className="supplies-empty">Выберите селлера</p>
        ) : loading && supplies.length === 0 ? (
          <p className="supplies-empty">Загрузка…</p>
        ) : supplies.length === 0 ? (
          <p className="supplies-empty">Поставок нет</p>
        ) : (
          <table className="supplies-table">
            <thead>
              <tr>
                <th>WB ID</th>
                <th>Статус</th>
                <th>Заказы</th>
                <th>Создана</th>
                <th>Действия</th>
              </tr>
            </thead>
            <tbody>
              {supplies.map((supply) => (
                <tr key={supply.id}>
                  <td>
                    <strong>{supply.wb_supply_id || '—'}</strong>
                  </td>
                  <td>
                    <span className={statusClass(supply.status)}>
                      {supply.status_display}
                    </span>
                  </td>
                  <td>
                    {supply.orders.map((order) => (
                      <div key={order.id} className="supplies-orders">
                        #{order.wb_order_id} · {order.barcode}
                        {order.cell_number ? ` · яч. ${order.cell_number}` : ''}
                        {order.requires_marking && (
                          <span
                            className={
                              order.marking_bound
                                ? 'marking-badge marking-badge--ok'
                                : 'marking-badge marking-badge--required'
                            }
                          >
                            {order.marking_bound ? 'ЧЗ ✓' : 'ЧЗ!'}
                          </span>
                        )}
                        {order.block_reason && (
                          <div className="supplies-block">{order.block_reason}</div>
                        )}
                      </div>
                    ))}
                  </td>
                  <td>{new Date(supply.created_at).toLocaleString('ru-RU')}</td>
                  <td>
                    <div className="supplies-actions">
                      {supply.can_deliver && (
                        <button
                          type="button"
                          className="btn btn--primary btn--sm"
                          onClick={() => handleDeliver(supply.id)}
                          disabled={loading}
                        >
                          В доставку
                        </button>
                      )}
                      {supply.status === 'confirmed' && (
                        <button
                          type="button"
                          className="btn btn--secondary btn--sm"
                          onClick={() => handleReprintBarcode(supply.id)}
                        >
                          Печать QR
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  )
}
