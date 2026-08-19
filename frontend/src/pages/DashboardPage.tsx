import { useCallback, useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { ProcessFlow } from '../components/ProcessFlow'
import { StatCard } from '../components/StatCard'
import {
  fetchOrderStats,
  syncOrders,
  type DashboardStats,
  type OrderStats,
} from '../api/orders'
import { useAuth } from '../context/AuthContext'

const STATS_POLL_MS = 60_000

function mergeDashboardStats(prev: OrderStats, patch: Partial<OrderStats>): OrderStats {
  return { ...prev, ...patch }
}

function statsFromSync(sync: DashboardStats): Partial<OrderStats> {
  return {
    new_orders: sync.new_orders,
    in_assembly: sync.in_assembly,
    in_delivery: sync.in_delivery,
    stats_source: 'cache',
    counts_synced_at: new Date().toISOString(),
  }
}

export function DashboardPage() {
  const { user, isAdmin, isManager, isSeller } = useAuth()
  const location = useLocation()
  const [stats, setStats] = useState<OrderStats>({
    orders_today: 0,
    in_picking: 0,
    new_orders: 0,
    sellers_count: 0,
    sku_count: 0,
  })
  const [syncing, setSyncing] = useState(false)
  const [statsLoading, setStatsLoading] = useState(false)
  const [syncError, setSyncError] = useState('')
  const [statsError, setStatsError] = useState('')

  const loadStats = useCallback(async () => {
    setStatsLoading(true)
    setStatsError('')
    try {
      const data = await fetchOrderStats()
      setStats(data)
    } catch (err) {
      setStatsError(err instanceof Error ? err.message : 'Не удалось загрузить счётчики')
    } finally {
      setStatsLoading(false)
    }
  }, [])

  useEffect(() => {
    if (location.pathname === '/') {
      loadStats()
    }
  }, [location.pathname, loadStats])

  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === 'visible') {
        loadStats()
      }
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [loadStats])

  useEffect(() => {
    const timer = window.setInterval(loadStats, STATS_POLL_MS)
    return () => window.clearInterval(timer)
  }, [loadStats])

  async function handleSync() {
    setSyncing(true)
    setSyncError('')
    try {
      const result = await syncOrders()
      if (result.dashboard_stats) {
        setStats((prev) => mergeDashboardStats(prev, statsFromSync(result.dashboard_stats!)))
      }
      await loadStats()
    } catch (err) {
      setSyncError(err instanceof Error ? err.message : 'Ошибка синхронизации')
    } finally {
      setSyncing(false)
    }
  }

  if (!user) return null

  const syncedLabel = stats.counts_synced_at
    ? `Сохранено в БД: ${new Date(stats.counts_synced_at).toLocaleString('ru-RU')}`
    : stats.stats_source === 'cache'
      ? 'Данные из кэша WB'
      : 'Нажмите «Обновить данные WB» для актуальных цифр'

  return (
    <>
      <header className="topbar">
        <div>
          <h1>Дашборд склада</h1>
          <p>
            {isSeller && user.seller_name
              ? `Кабинет селлера: ${user.seller_name}`
              : 'Обзор операций фулфилмента · автообновление табло каждую минуту'}
          </p>
          <p className="dashboard-sync-meta">
            {statsLoading ? 'Загрузка счётчиков…' : syncedLabel}
          </p>
        </div>
        <button
          type="button"
          className="btn btn--primary"
          onClick={handleSync}
          disabled={syncing}
        >
          {syncing ? 'Синхронизация WB…' : 'Обновить данные WB'}
        </button>
      </header>

      {syncError && <div className="dashboard-sync-msg dashboard-sync-msg--error">{syncError}</div>}
      {statsError && <div className="dashboard-sync-msg dashboard-sync-msg--error">{statsError}</div>}

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
