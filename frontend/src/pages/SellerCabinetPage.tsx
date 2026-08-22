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
        <section className="stats-grid">
          <StatCard label="Заказы сегодня" value={summary.orders_day} hint="FBS с ваших складов" tone="blue" />
          <StatCard label="За неделю" value={summary.orders_week} hint="FBS · последние 7 дней" tone="purple" />
          <StatCard label="За месяц" value={summary.orders_month} hint="FBS · с 1-го числа" tone="orange" />
          <StatCard label="Остаток (шт.)" value={summary.total_stock} hint={`${summary.sku_count} SKU на складе`} tone="green" />
        </section>
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
