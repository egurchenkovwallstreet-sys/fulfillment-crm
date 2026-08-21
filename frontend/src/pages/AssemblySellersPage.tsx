import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchAssemblySellers, type SellerAssemblyCounters } from '../api/assembly'
import { syncOrders } from '../api/orders'
import './AssemblyPage.css'

export function AssemblySellersPage() {
  const [sellers, setSellers] = useState<SellerAssemblyCounters[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [syncMessage, setSyncMessage] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setSellers(await fetchAssemblySellers())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка загрузки')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  async function handleSyncAll() {
    setLoading(true)
    setSyncMessage('')
    try {
      const result = await syncOrders()
      const fetched = result.fetched ?? result.results?.reduce((s, r) => s + (r.fetched ?? 0), 0) ?? 0
      const statusesUpdated = result.statuses_updated ?? result.results?.reduce((s, r) => s + (r.statuses_updated ?? 0), 0) ?? 0
      setSyncMessage(`Синхронизация завершена. Из WB: ${fetched}, статусов обновлено: ${statusesUpdated}`)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка синхронизации')
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <header className="topbar">
        <div>
          <h1>Сборка FBS</h1>
          <p>Выберите селлера для подготовки и сборки заказов</p>
        </div>
        <button type="button" className="btn btn--primary" onClick={handleSyncAll} disabled={loading}>
          Обновить из WB
        </button>
      </header>

      {error && <div className="alert alert--error">{error}</div>}
      {syncMessage && <div className="alert alert--success">{syncMessage}</div>}

      <section className="panel assembly-sellers">
        <table className="assembly-table">
          <thead>
            <tr>
              <th>Селлер</th>
              <th>Новые</th>
              <th>На сборке</th>
              <th>В доставке</th>
            </tr>
          </thead>
          <tbody>
            {sellers.length === 0 && (
              <tr>
                <td colSpan={4} className="assembly-table__empty">
                  Нет селлеров. Добавьте в админке.
                </td>
              </tr>
            )}
            {sellers.map((seller) => (
              <tr key={seller.id}>
                <td>
                  <Link to={`/assembly/${seller.id}`} className="assembly-seller-link">
                    {seller.company_name}
                  </Link>
                </td>
                <td>
                  <span className={`assembly-count${seller.new > 0 ? ' assembly-count--highlight' : ''}`}>
                    {seller.new}
                  </span>
                </td>
                <td>{seller.in_picking}</td>
                <td>{seller.in_delivery}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  )
}
