import { useCallback, useEffect, useMemo, useState } from 'react'
import { fetchAdminBilling, type AdminBillingSellerRow } from '../api/sellerAdmin'
import { formatMoney, WeeklyShipmentsPanel } from '../components/WeeklyShipmentsPanel'
import { uiHint } from '../utils/uiHint'
import '../pages/SellerCabinetPage.css'
import './AdminBillingPage.css'

type BillingMarketplace = 'wb' | 'ozon'

export function AdminBillingPage() {
  const [marketplace, setMarketplace] = useState<BillingMarketplace>('wb')
  const [data, setData] = useState<Awaited<ReturnType<typeof fetchAdminBilling>> | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [weekIndex, setWeekIndex] = useState(0)
  const [refreshing, setRefreshing] = useState(false)

  const load = useCallback(async (options?: { refresh?: boolean }) => {
    setLoading(true)
    setError('')
    try {
      const result = await fetchAdminBilling(marketplace, {
        refresh: options?.refresh,
        poll: true,
      })
      if (result.status === 'pending' || !result.combined) {
        setError(result.detail || 'Статистика загружается — попробуйте обновить через минуту')
        setData(null)
        setRefreshing(Boolean(result.refreshing))
        return
      }
      setData(result)
      setRefreshing(Boolean(result.refreshing))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка загрузки')
    } finally {
      setLoading(false)
    }
  }, [marketplace])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    setWeekIndex(0)
  }, [marketplace, data?.combined])

  const sellerRows = useMemo(() => {
    if (!data) return []
    return data.sellers ?? []
      .map((row) => {
        const shipWeek = row.weekly_shipments?.weeks[weekIndex]
        const storageWeek = row.liter_storage_chart?.weeks[weekIndex]
        const literShipWeek = row.liter_shipments_chart?.weeks[weekIndex]
        const isLiter = row.pricing_mode === 'per_liter'
        return {
          ...row,
          weekOrders: isLiter ? (literShipWeek?.total ?? 0) : (shipWeek?.total ?? 0),
          weekAmount: isLiter ? (literShipWeek?.total_amount ?? '0') : (shipWeek?.total_amount ?? '0'),
          weekSupplies: shipWeek?.supplies_count ?? 0,
          weekStorageAmount: storageWeek?.total_amount ?? '0',
        }
      })
      .sort((a, b) => Number(b.weekAmount) + Number(b.weekStorageAmount) - Number(a.weekAmount) - Number(a.weekStorageAmount))
  }, [data, weekIndex])

  const weekTotals = useMemo(() => {
    const ok = sellerRows.filter((row) => !row.error && row.weekly_shipments)
    const combinedWeek = data?.combined?.weeks[weekIndex]
    return {
      sellers: ok.length,
      orders: ok.reduce((sum, row) => sum + row.weekOrders, 0),
      supplies: combinedWeek?.supplies_count ?? ok.reduce((sum, row) => sum + row.weekSupplies, 0),
      amount: ok.reduce((sum, row) => sum + Number(row.weekAmount), 0),
    }
  }, [sellerRows, data?.combined?.weeks, weekIndex])

  const isOzon = marketplace === 'ozon'

  return (
    <>
      <header className="topbar">
        <div>
          <h1>Статистика отгрузок</h1>
          <p>
            Все селлеры · {isOzon ? 'отгрузки Ozon FBS' : 'отгрузки на склад WB'} · суммы по тарифам
          </p>
        </div>
        <div className="admin-billing-toolbar">
          <div className="admin-billing-tabs" role="tablist" aria-label="Маркетплейс">
            <button
              type="button"
              role="tab"
              aria-selected={marketplace === 'wb'}
              className={`admin-billing-tab${marketplace === 'wb' ? ' admin-billing-tab--active' : ''}`}
              onClick={() => setMarketplace('wb')}
              {...uiHint('Показать статистику отгрузок Wildberries по всем селлерам.')}
            >
              Wildberries
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={marketplace === 'ozon'}
              className={`admin-billing-tab${marketplace === 'ozon' ? ' admin-billing-tab--active' : ''}`}
              onClick={() => setMarketplace('ozon')}
              {...uiHint('Показать статистику отгрузок Ozon FBS по всем селлерам.')}
            >
              Ozon
            </button>
          </div>
          <button
            type="button"
            className="btn btn--ghost"
            onClick={() => void load({ refresh: true })}
            disabled={loading}
            {...uiHint('Запросить пересчёт статистики в фоне. Пока идёт расчёт, показываются последние сохранённые данные.')}
          >
            {loading ? 'Обновление…' : 'Обновить'}
          </button>
        </div>
      </header>

      {error && <div className="dashboard-sync-msg dashboard-sync-msg--error">{error}</div>}
      {refreshing && !error && (
        <div className="dashboard-sync-msg">
          Статистика пересчитывается в фоне
          {data?.cached_at ? ` · последние данные от ${new Date(data.cached_at).toLocaleString('ru-RU')}` : ''}
        </div>
      )}
      {loading && !data && (
        <p>
          {isOzon
            ? 'Загрузка… (данные считаются в фоне, это может занять до 2 минут)'
            : 'Загрузка… (данные считаются в фоне, запросы к WB могут занять несколько минут)'}
        </p>
      )}

      {data?.combined && (
        <WeeklyShipmentsPanel
          data={data.combined}
          title={isOzon ? 'Отгрузки Ozon — по штукам (итого)' : 'Отгрузки WB — по штукам (итого)'}
          hint={
            isOzon
              ? 'Селлеры с режимом «за единицу». Сумма — тариф × количество отгруженных единиц.'
              : 'Селлеры с режимом «за единицу». Заказы из поставок WB (done) × тариф за единицу.'
          }
          weekIndex={weekIndex}
          onWeekIndexChange={setWeekIndex}
        />
      )}

      {data?.combined_storage && (
        <WeeklyShipmentsPanel
          data={data.combined_storage}
          title="Хранение — все селлеры (итого)"
          hint="Ежедневные начисления по остатку × литры (товары с габаритами). Не зависит от режима отгрузки."
          weekIndex={weekIndex}
          onWeekIndexChange={setWeekIndex}
        />
      )}

      {data && (
        <section className="panel admin-billing-sellers">
          <div className="admin-billing-sellers__head">
            <h2 className="section-title">По селлерам</h2>
            <p className="admin-billing-sellers__meta">
              {weekTotals.sellers} селлеров ·{' '}
              {weekTotals.orders} {isOzon ? 'единиц отгружено' : 'заказов отгружено'} ·{' '}
              {weekTotals.supplies} {isOzon ? 'отгрузок' : 'поставок'} ·{' '}
              {formatMoney(weekTotals.amount)}
            </p>
          </div>

          <div className="sellers-table-scroll">
            <table className="sellers-table admin-billing-table">
              <thead>
                <tr>
                  <th>Селлер</th>
                  <th>Режим</th>
                  <th>{isOzon ? 'Единиц отгружено' : 'Заказов отгружено'}</th>
                  <th>{isOzon ? 'Отгрузок' : 'Поставок'}</th>
                  <th>Отгрузка</th>
                  <th>Хранение</th>
                  <th>Статус</th>
                </tr>
              </thead>
              <tbody>
                {sellerRows.map((row) => (
                  <SellerBillingRow key={row.seller_id} row={row} />
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </>
  )
}

function SellerBillingRow({
  row,
}: {
  row: AdminBillingSellerRow & {
    weekOrders: number
    weekAmount: string
    weekSupplies: number
    weekStorageAmount: string
  }
}) {
  if (row.error) {
    return (
      <tr>
        <td><strong>{row.company_name}</strong></td>
        <td colSpan={5}>—</td>
        <td><span className="sellers-tag sellers-tag--warn">{row.error}</span></td>
      </tr>
    )
  }

  const modeLabel = row.pricing_mode === 'per_liter' ? 'Объём' : 'Штуки'

  return (
    <tr>
      <td><strong>{row.company_name}</strong></td>
      <td>{modeLabel}</td>
      <td>{row.weekOrders}</td>
      <td>{row.weekSupplies}</td>
      <td>{formatMoney(row.weekAmount)}</td>
      <td>{formatMoney(row.weekStorageAmount)}</td>
      <td><span className="sellers-tag sellers-tag--ok">OK</span></td>
    </tr>
  )
}
