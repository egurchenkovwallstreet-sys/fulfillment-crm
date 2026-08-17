import { useCallback, useEffect, useState } from 'react'
import {
  fetchOrders,
  fetchPickList,
  fetchPickLists,
  generatePickList,
  syncOrders,
  type Order,
  type PickList,
  type PickListBrief,
} from '../api/orders'
import { fetchSellers, type Seller } from '../api/warehouse'
import './OrdersPage.css'

const STATUS_LABELS: Record<string, string> = {
  new: 'Новый',
  in_picking: 'В подборе',
  assembled: 'Собран',
  label_printed: 'Этикетка',
  marked: 'ЧЗ',
  in_supply: 'В поставке',
  shipped: 'Отправлен',
  cancelled: 'Отменён',
}

export function OrdersPage() {
  const [sellers, setSellers] = useState<Seller[]>([])
  const [sellerId, setSellerId] = useState<number | ''>('')
  const [orders, setOrders] = useState<Order[]>([])
  const [pickLists, setPickLists] = useState<PickListBrief[]>([])
  const [activePickList, setActivePickList] = useState<PickList | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  const loadData = useCallback(async (selectedSeller?: number) => {
    setLoading(true)
    setError('')
    try {
      const [sellersData, ordersData, listsData] = await Promise.all([
        fetchSellers(),
        fetchOrders(selectedSeller ? { seller_id: selectedSeller } : undefined),
        fetchPickLists(selectedSeller),
      ])
      setSellers(sellersData)
      setOrders(ordersData)
      setPickLists(listsData)
      if (listsData.length > 0) {
        const detail = await fetchPickList(listsData[0].id)
        setActivePickList(detail)
      } else {
        setActivePickList(null)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка загрузки')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadData(sellerId === '' ? undefined : sellerId)
  }, [sellerId, loadData])

  async function handleSync() {
    setError('')
    setSuccess('')
    setLoading(true)
    try {
      const result = await syncOrders(sellerId === '' ? undefined : sellerId)
      if (result.errors?.length) {
        setError(result.errors.map((e) => e.error).join('; '))
      }
      const created = result.created ?? result.results?.reduce((s, r) => s + (r.created ?? 0), 0) ?? 0
      setSuccess(`Синхронизация завершена. Новых заказов: ${created}`)
      await loadData(sellerId === '' ? undefined : sellerId)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка синхронизации')
    } finally {
      setLoading(false)
    }
  }

  async function handleGeneratePickList() {
    if (!sellerId) {
      setError('Выберите селлера для формирования листа подбора')
      return
    }
    setError('')
    setSuccess('')
    setLoading(true)
    try {
      const pickList = await generatePickList(sellerId)
      setActivePickList(pickList)
      setSuccess(`Лист подбора #${pickList.id} сформирован (${pickList.total_quantity} шт.)`)
      await loadData(sellerId)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка формирования')
    } finally {
      setLoading(false)
    }
  }

  async function handleSelectPickList(id: number) {
    setLoading(true)
    try {
      const detail = await fetchPickList(id)
      setActivePickList(detail)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка загрузки листа')
    } finally {
      setLoading(false)
    }
  }

  function handlePrint() {
    window.print()
  }

  return (
    <>
      <header className="topbar">
        <div>
          <h1>Заказы FBS</h1>
          <p>Синхронизация с Wildberries и лист подбора по ячейкам</p>
        </div>
        <div className="topbar__actions">
          <button type="button" className="btn btn--secondary" onClick={handleSync} disabled={loading}>
            Обновить из WB
          </button>
          <button type="button" className="btn btn--primary" onClick={handleGeneratePickList} disabled={loading}>
            Сформировать лист подбора
          </button>
        </div>
      </header>

      {error && <div className="alert alert--error">{error}</div>}
      {success && <div className="alert alert--success">{success}</div>}

      <section className="orders-toolbar panel">
        <label className="orders-field">
          Селлер
          <select
            value={sellerId}
            onChange={(e) => setSellerId(e.target.value ? Number(e.target.value) : '')}
          >
            <option value="">Все селлеры</option>
            {sellers.map((s) => (
              <option key={s.id} value={s.id}>
                {s.company_name}
              </option>
            ))}
          </select>
        </label>
      </section>

      <div className="orders-grid">
        <section className="panel orders-table-panel">
          <h2 className="section-title">Заказы ({orders.length})</h2>
          <div className="orders-table-wrap">
            <table className="orders-table">
              <thead>
                <tr>
                  <th>WB ID</th>
                  <th>Баркод</th>
                  <th>Ячейка</th>
                  <th>Селлер</th>
                  <th>Статус</th>
                </tr>
              </thead>
              <tbody>
                {orders.length === 0 && (
                  <tr>
                    <td colSpan={5} className="orders-table__empty">
                      Нет заказов. Нажмите «Обновить из WB».
                    </td>
                  </tr>
                )}
                {orders.map((order) => (
                  <tr key={order.id}>
                    <td>{order.wb_order_id}</td>
                    <td><code>{order.barcode}</code></td>
                    <td>{order.cell_number || '—'}</td>
                    <td>{order.seller_name}</td>
                    <td>
                      <span className={`status-badge status-badge--${order.status}`}>
                        {STATUS_LABELS[order.status] ?? order.status_display}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="panel pick-list-panel">
          <div className="pick-list-header">
            <h2 className="section-title">Лист подбора</h2>
            {activePickList && (
              <button type="button" className="btn btn--ghost pick-list-print" onClick={handlePrint}>
                Печать
              </button>
            )}
          </div>

          {pickLists.length > 1 && (
            <div className="pick-list-tabs">
              {pickLists.map((pl) => (
                <button
                  key={pl.id}
                  type="button"
                  className={`pick-list-tab${activePickList?.id === pl.id ? ' pick-list-tab--active' : ''}`}
                  onClick={() => handleSelectPickList(pl.id)}
                >
                  #{pl.id} · {pl.seller_name}
                </button>
              ))}
            </div>
          )}

          {activePickList ? (
            <div className="pick-list-print-area">
              <p className="pick-list-meta">
                Селлер: <strong>{activePickList.seller_name}</strong>
                {' · '}
                {new Date(activePickList.created_at).toLocaleString('ru-RU')}
                {' · '}
                {activePickList.total_quantity} шт.
              </p>
              <table className="orders-table pick-list-table">
                <thead>
                  <tr>
                    <th>Ячейка</th>
                    <th>Баркод</th>
                    <th>Собрать</th>
                  </tr>
                </thead>
                <tbody>
                  {activePickList.items.map((item) => (
                    <tr key={item.id}>
                      <td><strong>{item.cell_number}</strong></td>
                      <td><code>{item.barcode}</code></td>
                      <td className="pick-list-qty">{item.quantity} шт.</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="orders-table__empty">
              Выберите селлера и нажмите «Сформировать лист подбора».
            </p>
          )}
        </section>
      </div>
    </>
  )
}
