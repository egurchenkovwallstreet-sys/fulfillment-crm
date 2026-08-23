import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  fetchSellerCabinet,
  type SellerBarcodeItem,
  type SellerCabinetResponse,
} from '../api/sellerCabinet'
import { StatCard } from '../components/StatCard'
import './SellerCabinetPage.css'

const STOCK_LABELS: Record<string, string> = {
  critical: 'Догрузить',
  sufficient: 'Норма',
  excess: 'Много',
}

function formatDays(days: number | null): string {
  if (days === null) return '—'
  if (days === 0) return '0'
  return String(days)
}

function formatShortDate(iso: string): string {
  return new Date(`${iso}T12:00:00`).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })
}

function StockBadge({ level }: { level: SellerBarcodeItem['stock_level'] }) {
  return <span className={`stock-badge stock-badge--${level}`}>{STOCK_LABELS[level] ?? level}</span>
}

export function SellerCabinetPage() {
  const [data, setData] = useState<SellerCabinetResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setData(await fetchSellerCabinet())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка загрузки')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const summary = data?.summary

  return (
    <>
      <header className="topbar">
        <div>
          <h1>Кабинет селлера</h1>
          <p>{data?.seller.company_name ?? 'FBS-заказы с обслуживаемых складов · остатки на фулфилменте'}</p>
        </div>
        <button type="button" className="btn btn--ghost" onClick={load} disabled={loading}>
          {loading ? 'Обновление…' : 'Обновить'}
        </button>
      </header>

      {error && <div className="dashboard-sync-msg dashboard-sync-msg--error">{error}</div>}

      {summary && (
        <>
          <section className="stats-grid">
            <StatCard
              label="Заказы сегодня"
              value={summary.orders_day.current}
              hint="FBS · календарный день (МСК)"
              tone="blue"
              trend={summary.orders_day}
              trendLabel="к вчера"
            />
            <StatCard
              label="За неделю"
              value={summary.orders_week.current}
              hint="FBS · календарная неделя пн–вс"
              tone="purple"
              trend={summary.orders_week}
              trendLabel="к прошлой неделе"
            />
            <StatCard
              label="За месяц"
              value={summary.orders_month.current}
              hint="FBS · с 1-го числа (МСК)"
              tone="orange"
              trend={summary.orders_month}
              trendLabel="к прошлому месяцу"
            />
            <StatCard label="Остаток (шт.)" value={summary.total_stock} hint={`${summary.sku_count} SKU на складе`} tone="green" />
          </section>

          {data?.wb_stages && (
            <section className="stats-grid stats-grid--stages">
              <StatCard label="Новые" value={data.wb_stages.new} hint="Как в сборке FBS" tone="red" />
              <StatCard label="На сборке" value={data.wb_stages.in_picking} hint="Как в сборке FBS" tone="orange" />
              <StatCard label="В доставке" value={data.wb_stages.in_delivery} hint="Как в сборке FBS" tone="blue" />
            </section>
          )}

          {data?.weekly_shipments && (
            <section className="panel seller-weekly-shipments">
              <div className="seller-weekly-shipments__head">
                <div>
                  <h2 className="section-title">Отгрузки на склад WB</h2>
                  <p className="seller-weekly-shipments__hint">
                    Календарная неделя {formatShortDate(data.weekly_shipments.week_start)} — {formatShortDate(data.weekly_shipments.week_end)} (МСК).
                    Считаются заказы из поставок, переданных/отсканированных WB (done).
                  </p>
                </div>
                <div className="seller-weekly-shipments__total">
                  <span className="seller-weekly-shipments__total-label">Итого за неделю</span>
                  <strong className="seller-weekly-shipments__total-value">{data.weekly_shipments.total}</strong>
                </div>
              </div>
              <div className="seller-chart seller-weekly-chart">
                {data.weekly_shipments.days.map((day) => {
                  const max = Math.max(...data.weekly_shipments.days.map((item) => item.orders), 1)
                  const height = Math.max(4, Math.round((day.orders / max) * 140))
                  const isToday = day.date === data.weekly_shipments.today
                  return (
                    <div key={day.date} className={`seller-chart__col${isToday ? ' seller-chart__col--today' : ''}`}>
                      <span className="seller-chart__value">{day.orders}</span>
                      <div className="seller-chart__bar" style={{ height: `${height}px` }} />
                      <span className="seller-chart__label">{day.weekday}</span>
                    </div>
                  )
                })}
              </div>
            </section>
          )}
        </>
      )}

      <section className="panel seller-cabinet-table-wrap">
        <h2 className="section-title">Товары и остатки</h2>
        <p className="seller-cabinet-legend">
          <span className="stock-badge stock-badge--critical">Догрузить</span> — меньше 5 дней запаса
          <span className="stock-badge stock-badge--sufficient">Норма</span> — 5–15 дней
          <span className="stock-badge stock-badge--excess">Много</span> — больше 15 дней
        </p>

        {loading && !data && <p>Загрузка…</p>}

        {data && data.items.length === 0 && (
          <p className="seller-cabinet-empty">На складе пока нет ваших товаров.</p>
        )}

        {data && data.items.length > 0 && (
          <div className="seller-cabinet-table-scroll">
            <table className="seller-cabinet-table">
              <thead>
                <tr>
                  <th>Товар</th>
                  <th>Штрихкод</th>
                  <th>Остаток</th>
                  <th>Заказы д/н/м</th>
                  <th>Ср. в день (7д)</th>
                  <th>Хватит на</th>
                  <th>Статус</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((item) => (
                  <tr key={item.barcode} className={`seller-cabinet-row seller-cabinet-row--${item.stock_level}`}>
                    <td>
                      <Link to={`/cabinet/${encodeURIComponent(item.barcode)}`} className="seller-cabinet-link">
                        {item.name}
                      </Link>
                    </td>
                    <td className="mono">{item.barcode}</td>
                    <td>{item.stock_quantity}</td>
                    <td>
                      {item.orders_day} / {item.orders_week} / {item.orders_month}
                    </td>
                    <td>{item.avg_daily_sales}</td>
                    <td>{formatDays(item.days_remaining)} дн.</td>
                    <td>
                      <StockBadge level={item.stock_level} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  )
}
