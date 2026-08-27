import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchAssemblySellers, type SellerAssemblyCounters } from '../api/assembly'
import { syncOrders } from '../api/orders'
import { useMarketplace } from '../context/MarketplaceContext'
import './AssemblyPage.css'

export function AssemblySellersPage() {
  const { marketplace } = useMarketplace()
  const [sellers, setSellers] = useState<SellerAssemblyCounters[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [syncMessage, setSyncMessage] = useState('')

  const [syncing, setSyncing] = useState(false)

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

  useEffect(() => {
    let cancelled = false

    async function backgroundSync() {
      setSyncing(true)
      setSyncMessage('')
      try {
        const result = await syncOrders(undefined, 'quick')
        if (!cancelled) {
          const fetched = result.fetched ?? result.results?.reduce((s, r) => s + (r.fetched ?? 0), 0) ?? 0
          const statusesUpdated = result.statuses_updated ?? result.results?.reduce((s, r) => s + (r.statuses_updated ?? 0), 0) ?? 0
          setSyncMessage(
            marketplace === 'ozon'
              ? `Счётчики Ozon обновлены`
              : `Синхронизация с WB: заказов ${fetched}, статусов обновлено ${statusesUpdated}`,
          )
          await load()
        }
      } catch (err) {
        if (!cancelled) {
          setSyncMessage('')
          setError(err instanceof Error ? err.message : 'Ошибка синхронизации')
        }
      } finally {
        if (!cancelled) {
          setSyncing(false)
        }
      }
    }

    backgroundSync()
    return () => {
      cancelled = true
    }
  }, [load])

  async function handleSyncAll() {
    setLoading(true)
    setSyncMessage('')
    try {
      const result = await syncOrders(undefined, 'quick')
      const fetched = result.fetched ?? result.results?.reduce((s, r) => s + (r.fetched ?? 0), 0) ?? 0
      const statusesUpdated = result.statuses_updated ?? result.results?.reduce((s, r) => s + (r.statuses_updated ?? 0), 0) ?? 0
      setSyncMessage(
        marketplace === 'ozon'
          ? 'Счётчики Ozon обновлены'
          : `Синхронизация завершена. Из WB: ${fetched}, статусов обновлено: ${statusesUpdated}`,
      )
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
          <h1>Сборка FBS {marketplace === 'ozon' ? 'Ozon' : 'WB'}</h1>
          <p>
            {marketplace === 'ozon'
              ? 'Селлеры Ozon. Откройте кабинет: скан баркода → на сборке → в доставку.'
              : 'Выберите селлера для подготовки и сборки заказов'}
          </p>
        </div>
        <button type="button" className="btn btn--primary" onClick={handleSyncAll} disabled={loading || syncing}>
          {syncing
            ? marketplace === 'ozon'
              ? 'Обновление Ozon…'
              : 'Синхронизация WB…'
            : marketplace === 'ozon'
              ? 'Обновить из Ozon'
              : 'Обновить из WB'}
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
            {sellers.length === 0 && !loading && !syncing && (
              <tr>
                <td colSpan={4} className="assembly-table__empty">
                  Нет селлеров с этим маркетплейсом. Отметьте WB или Ozon в разделе «Селлеры».
                </td>
              </tr>
            )}
            {loading && sellers.length === 0 && (
              <tr>
                <td colSpan={4} className="assembly-table__empty">
                  Загрузка…
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
