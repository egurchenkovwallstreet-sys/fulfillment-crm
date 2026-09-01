import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchAssemblySellers, type SellerAssemblyCounters } from '../api/assembly'
import { syncOrders } from '../api/orders'
import { useMarketplace } from '../context/MarketplaceContext'
import { readAssemblySellersCache, writeAssemblySellersCache } from '../utils/assemblyCache'
import { uiHint } from '../utils/uiHint'
import './AssemblyPage.css'

export function AssemblySellersPage() {
  const { marketplace } = useMarketplace()
  const [sellers, setSellers] = useState<SellerAssemblyCounters[]>(
    () => readAssemblySellersCache(marketplace) ?? [],
  )
  const [loading, setLoading] = useState(() => !(readAssemblySellersCache(marketplace)?.length))
  const [error, setError] = useState('')
  const [syncMessage, setSyncMessage] = useState('')
  const [syncing, setSyncing] = useState(false)
  const bgSyncStartedRef = useRef(false)

  const load = useCallback(async () => {
    setError('')
    try {
      const list = await fetchAssemblySellers()
      setSellers(list)
      writeAssemblySellersCache(marketplace, list)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка загрузки')
    }
  }, [marketplace])

  useEffect(() => {
    let cancelled = false
    bgSyncStartedRef.current = false

    async function initialLoad() {
      setLoading(sellers.length === 0)
      try {
        await load()
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    void initialLoad()
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [marketplace])

  useEffect(() => {
    if (bgSyncStartedRef.current) return
    bgSyncStartedRef.current = true

    let cancelled = false
    const timer = window.setTimeout(() => {
      void (async () => {
        setSyncing(true)
        setSyncMessage('')
        try {
          const result = await syncOrders(undefined, 'quick')
          if (cancelled) return
          const fetched = result.fetched ?? result.results?.reduce((s, r) => s + (r.fetched ?? 0), 0) ?? 0
          const statusesUpdated = result.statuses_updated ?? result.results?.reduce((s, r) => s + (r.statuses_updated ?? 0), 0) ?? 0
          await load()
          if (cancelled) return
          setSyncMessage(
            marketplace === 'ozon'
              ? 'Счётчики Ozon обновлены'
              : `Синхронизация с WB: заказов ${fetched}, статусов обновлено ${statusesUpdated}`,
          )
        } catch (err) {
          if (!cancelled) {
            setSyncMessage('')
            if (!sellers.length) {
              setError(err instanceof Error ? err.message : 'Ошибка синхронизации')
            }
          }
        } finally {
          if (!cancelled) setSyncing(false)
        }
      })()
    }, 600)

    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [marketplace])

  async function handleSyncAll() {
    setLoading(true)
    setSyncMessage('')
    setError('')
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
            {syncing ? ' · синхронизация с маркетплейсом…' : ''}
            {loading && sellers.length > 0 ? ' · обновление списка…' : ''}
          </p>
        </div>
        <button type="button" className="btn btn--primary" onClick={handleSyncAll} disabled={loading || syncing} {...uiHint(marketplace === 'ozon' ? 'Обновить счётчики заказов Ozon для всех селлеров.' : 'Синхронизировать заказы и статусы WB для всех селлеров.')}>
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
            {sellers.length === 0 && (loading || syncing) && (
              <tr>
                <td colSpan={4} className="assembly-table__empty">
                  Загрузка списка селлеров…
                </td>
              </tr>
            )}
            {sellers.map((seller) => (
              <tr key={seller.id}>
                <td>
                  <Link to={`/assembly/${seller.id}`} className="assembly-seller-link" {...uiHint(`Открыть сборку FBS для селлера ${seller.company_name}.`)}>
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
