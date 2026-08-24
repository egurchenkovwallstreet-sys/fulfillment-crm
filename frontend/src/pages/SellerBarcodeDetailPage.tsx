import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { fetchSellerBarcodeDetail, type SellerBarcodeDetail } from '../api/sellerCabinet'
import { ProductPhotoThumb } from '../components/ProductPhotoThumb'
import './SellerCabinetPage.css'

const STOCK_LABELS: Record<string, string> = {
  urgent: 'Срочно догрузить',
  restock: 'Догрузить',
  sufficient: 'Норма',
  excess: 'Много',
}

export function SellerBarcodeDetailPage() {
  const { barcode } = useParams<{ barcode: string }>()
  const [item, setItem] = useState<SellerBarcodeDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    if (!barcode) return
    setLoading(true)
    setError('')
    try {
      setItem(await fetchSellerBarcodeDetail(barcode))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Товар не найден')
      setItem(null)
    } finally {
      setLoading(false)
    }
  }, [barcode])

  useEffect(() => {
    load()
  }, [load])

  const maxOrders = item ? Math.max(1, ...item.daily_orders.map((d) => d.orders)) : 1

  return (
    <>
      <header className="topbar">
        <div>
          <p className="seller-detail-back">
            <Link to="/cabinet">← Кабинет</Link>
          </p>
          <h1>{item?.name ?? 'Товар'}</h1>
          <p className="seller-cabinet-barcode-cell">
            {item?.tech_size && <strong className="seller-cabinet-eu-size">{item.tech_size}</strong>}
            <span className="mono">{barcode}</span>
          </p>
        </div>
      </header>

      {error && <div className="dashboard-sync-msg dashboard-sync-msg--error">{error}</div>}
      {loading && <p>Загрузка…</p>}

      {item && (
        <>
          {item.photo_url && (
            <section className="panel seller-detail-photo">
              <ProductPhotoThumb url={item.photo_url} alt={item.name} />
            </section>
          )}
          <section className="stats-grid seller-detail-stats">
            <article className="stat-card stat-card--green">
              <p className="stat-card__label">Остаток на складе</p>
              <p className="stat-card__value">{item.stock_quantity}</p>
            </article>
            <article className="stat-card stat-card--blue">
              <p className="stat-card__label">Средние продажи</p>
              <p className="stat-card__value">{item.avg_daily_sales}</p>
              <p className="stat-card__hint">заказов в сутки за {item.sales_lookback_days} дн.</p>
            </article>
            <article className={`stat-card stat-card--${item.stock_level === 'urgent' || item.stock_level === 'restock' ? 'red' : item.stock_level === 'sufficient' ? 'green' : 'orange'}`}>
              <p className="stat-card__label">Хватит на</p>
              <p className="stat-card__value">
                {item.days_remaining === null ? '—' : `${item.days_remaining} дн.`}
              </p>
              <p className="stat-card__hint">{STOCK_LABELS[item.stock_level] ?? item.stock_level}</p>
            </article>
          </section>

          <section className="panel">
            <h2 className="section-title">Заказы за {item.sales_lookback_days} дней</h2>
            <div className="seller-chart">
              {item.daily_orders.map((day) => (
                <div key={day.date} className="seller-chart__col">
                  <div
                    className="seller-chart__bar"
                    style={{ height: `${(day.orders / maxOrders) * 100}%` }}
                    title={`${day.orders} заказов`}
                  />
                  <span className="seller-chart__label">
                    {new Date(day.date).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })}
                  </span>
                  <span className="seller-chart__value">{day.orders}</span>
                </div>
              ))}
            </div>
          </section>
        </>
      )}
    </>
  )
}
