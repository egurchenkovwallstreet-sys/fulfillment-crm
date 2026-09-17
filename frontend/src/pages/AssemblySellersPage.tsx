import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchAssemblySellers, type SellerAssemblyCounters } from '../api/assembly'
import { syncOrders } from '../api/orders'
import { useMarketplace } from '../context/MarketplaceContext'
import { useCrmNotice } from '../context/CrmNoticeContext'
import { readAssemblySellersCache, writeAssemblySellersCache } from '../utils/assemblyCache'
import { uiHint } from '../utils/uiHint'
import './AssemblyPage.css'

const ASSEMBLY_SELLERS_POLL_MS = 60_000

export function AssemblySellersPage() {
  const { marketplace } = useMarketplace()
  const { showSuccess, showError } = useCrmNotice()
  const [sellers, setSellers] = useState<SellerAssemblyCounters[]>(
    () => readAssemblySellersCache(marketplace) ?? [],
  )
  const [loading, setLoading] = useState(() => !(readAssemblySellersCache(marketplace)?.length))
  const [syncing, setSyncing] = useState(false)
  const loadInFlightRef = useRef(false)

  const load = useCallback(async (opts?: { silent?: boolean; refresh?: boolean }) => {
    if (loadInFlightRef.current) return
    loadInFlightRef.current = true
    try {
      const list = await fetchAssemblySellers({ refresh: opts?.refresh })
      setSellers(list)
      writeAssemblySellersCache(marketplace, list)
    } catch (err) {
      if (!opts?.silent) {
        showError('Загрузка', err instanceof Error ? err.message : 'Ошибка загрузки')
      }
    } finally {
      loadInFlightRef.current = false
    }
  }, [marketplace, showError])

  useEffect(() => {
    let cancelled = false
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
    const tick = () => {
      if (document.visibilityState !== 'visible') return
      void load({ silent: true })
    }
    const timer = window.setInterval(tick, ASSEMBLY_SELLERS_POLL_MS)
    const onVisible = () => {
      if (document.visibilityState === 'visible') void load({ silent: true })
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [load])

  async function handleSyncAll() {
    setSyncing(true)
    try {
      const deliveryResult = await syncOrders(undefined, 'delivery', { background: false })
      const scanInfo = deliveryResult.supply_scan
      const scanned = scanInfo?.supplies_scanned ?? 0
      const closed = scanInfo?.orders_closed ?? 0
      const pending = scanInfo?.pending_supplies ?? '?'
      if (deliveryResult.scan_error) {
        showError('ScanDt', deliveryResult.scan_error)
      }
      const result = await syncOrders(undefined, 'quick')
      const fetched = result.fetched ?? result.results?.reduce((s, r) => s + (r.fetched ?? 0), 0) ?? 0
      const statusesUpdated = result.statuses_updated ?? result.results?.reduce((s, r) => s + (r.statuses_updated ?? 0), 0) ?? 0
      showSuccess(
        'Синхронизация',
        marketplace === 'ozon'
          ? 'Счётчики Ozon обновлены'
          : `ScanDt: ${scanned}/${pending} поставок, ${closed} заказов закрыто. WB: ${fetched} новых, статусов ${statusesUpdated}`,
      )
      await load({ refresh: true })
    } catch (err) {
      showError('Синхронизация', err instanceof Error ? err.message : 'Ошибка синхронизации')
    } finally {
      setSyncing(false)
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
