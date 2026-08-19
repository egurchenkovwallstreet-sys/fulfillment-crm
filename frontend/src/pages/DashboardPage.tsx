import { useCallback, useEffect, useState } from 'react'
import { ProcessFlow } from '../components/ProcessFlow'
import { StatCard } from '../components/StatCard'
import { fetchOrderStats, syncOrders, type OrderStats } from '../api/orders'
import { useAuth } from '../context/AuthContext'

export function DashboardPage() {
  const { user, isAdmin, isManager, isSeller } = useAuth()
  const [stats, setStats] = useState<OrderStats>({
    orders_today: 0,
    in_picking: 0,
    new_orders: 0,
    sellers_count: 0,
    sku_count: 0,
  })
  const [syncing, setSyncing] = useState(false)
  const [syncMessage, setSyncMessage] = useState('')

  const loadStats = useCallback(async () => {
    try {
      const data = await fetchOrderStats()
      setStats(data)
    } catch {
      // stats optional on first load
    }
  }, [])

  useEffect(() => {
    loadStats()
  }, [loadStats])

  async function handleSync() {
    setSyncing(true)
    setSyncMessage('')
    try {
      const result = await syncOrders()
      const created = result.created ?? result.results?.reduce((s, r) => s + (r.created ?? 0), 0) ?? 0
      const fetched = result.fetched ?? result.results?.reduce((s, r) => s + (r.fetched ?? 0), 0) ?? 0
      const rawTotal = result.raw_total ?? result.results?.reduce((s, r) => s + (r.raw_total ?? 0), 0) ?? fetched
      const statusesUpdated = result.statuses_updated ?? result.results?.reduce((s, r) => s + (r.statuses_updated ?? 0), 0) ?? 0
      const reconciled = result.reconciled ?? result.results?.reduce((s, r) => s + (r.reconciled ?? 0), 0) ?? 0
      const syncVersion = result.sync_version ?? result.results?.[0]?.sync_version
      const statusError = result.status_error ?? result.results?.[0]?.status_error
      const wbCounts = result.wb_counts ?? result.results?.[0]?.wb_counts
      const liveCounts = result.live_counts ?? result.results?.[0]?.live_counts
      const inDelivery = liveCounts?.in_delivery ?? wbCounts?.in_delivery
      const deliveryAll = result.delivery_all ?? result.results?.[0]?.delivery_all
      const breakdown = result.delivery_breakdown ?? result.results?.[0]?.delivery_breakdown
      let msg = `[${syncVersion ?? '?'}] В WB ${rawTotal} заказов, загружено ${fetched}, новых ${created}`
      msg += `, WB-полей ${statusesUpdated}, сверка ${reconciled}`
      if (statusError) msg += `. ОШИБКА: ${statusError}`
      if (inDelivery !== undefined) {
        msg += `. В доставке (sorted/30д): ${inDelivery}`
        if (deliveryAll !== undefined && deliveryAll !== inDelivery) {
          msg += `, всего sorted в API: ${deliveryAll}`
        }
      }
      if (breakdown && typeof breakdown === 'object') {
        const extra = Object.entries(breakdown)
          .filter(([k]) => k !== 'sorted')
          .map(([k, v]) => `${k}: ${v}`)
          .join(', ')
        if (extra) msg += `. Прочие complete: ${extra}`
      }
      const reconcile = result.reconcile ?? result.results?.[0]?.reconcile
      if (reconcile?.shipped_not_sorted) {
        msg += `, убрано ${reconcile.shipped_not_sorted}`
      }
      setSyncMessage(msg)
      await loadStats()
    } catch (err) {
      setSyncMessage(err instanceof Error ? err.message : 'Ошибка синхронизации')
    } finally {
      setSyncing(false)
    }
  }

  if (!user) return null

  return (
    <>
      <header className="topbar">
        <div>
          <h1>Дашборд склада</h1>
          <p>
            {isSeller && user.seller_name
              ? `Кабинет селлера: ${user.seller_name}`
              : 'Обзор операций фулфилмента · автообновление каждые 15 мин'}
          </p>
        </div>
        <button
          type="button"
          className="btn btn--primary"
          onClick={handleSync}
          disabled={syncing}
        >
          {syncing ? 'Обновление…' : 'Обновить данные WB'}
        </button>
      </header>

      {syncMessage && <div className="dashboard-sync-msg">{syncMessage}</div>}

      <section className="stats-grid">
        <StatCard
          label="Новые заказы"
          value={String(stats.new_orders)}
          hint={isSeller ? 'Ваши новые заказы' : 'Статус «Новый» в WB'}
          tone="red"
        />
        {isAdmin && (
          <StatCard
            label="Селлеров"
            value={String(stats.sellers_count ?? '—')}
            hint="Подключено к API"
            tone="purple"
          />
        )}
        {(isAdmin || isManager) && (
          <>
            <StatCard
              label="На сборке"
              value={String(stats.in_assembly ?? stats.in_picking)}
              hint="Статус «На сборке» в WB"
              tone="orange"
            />
            <StatCard
              label="В доставке"
              value={String(stats.in_delivery ?? 0)}
              hint="Статус «В доставке» в WB"
              tone="blue"
            />
          </>
        )}
        <StatCard
          label={isSeller ? 'Мои остатки (SKU)' : 'Остатков (SKU)'}
          value={String(stats.sku_count)}
          hint="По ячейкам склада"
          tone="green"
        />
      </section>

      {(isAdmin || isManager) && <ProcessFlow />}

      <section className="panels">
        <div className="panel">
          <h2 className="section-title">Ваш доступ</h2>
          <div className="roles-grid">
            {isAdmin && (
              <article className="role-card role-card--admin">
                <h3>Администратор</h3>
                <p>Селлеры, финансы, цены, отчёты, полный доступ к системе</p>
              </article>
            )}
            {isManager && (
              <article className="role-card role-card--manager">
                <h3>Менеджер склада</h3>
                <p>Приёмка, сборка, поставки — без цен и финансовых данных</p>
              </article>
            )}
            {isSeller && (
              <article className="role-card role-card--seller">
                <h3>Селлер</h3>
                <p>Только ваши остатки и заказы, без данных других селлеров</p>
              </article>
            )}
          </div>
        </div>

        <div className="panel panel--accent">
          <h2 className="section-title">Статус разработки</h2>
          <ul className="checklist">
            <li className="checklist__item checklist__item--done">Авторизация JWT + роли</li>
            <li className="checklist__item checklist__item--done">Модуль приёмки товара</li>
            <li className="checklist__item checklist__item--done">Модуль заказов и листа подбора</li>
            <li className="checklist__item">Интеграция Wildberries FBS (токены)</li>
            <li className="checklist__item">Печать этикеток Xprinter</li>
          </ul>
        </div>
      </section>
    </>
  )
}
