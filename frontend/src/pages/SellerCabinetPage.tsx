import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  fetchSellerCabinet,
  type SellerBarcodeItem,
  type SellerCabinetResponse,
  type SellerWeeklyShipmentWeek,
} from '../api/sellerCabinet'
import { useMarketplace } from '../context/MarketplaceContext'
import { StatCard } from '../components/StatCard'
import { ProductPhotoThumb } from '../components/ProductPhotoThumb'
import { hintWrapProps, uiHint } from '../utils/uiHint'
import './SellerCabinetPage.css'

const STOCK_LABELS: Record<string, string> = {
  urgent: 'Срочно догрузить',
  restock: 'Догрузить',
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

function formatMoney(value: string | number): string {
  const amount = typeof value === 'string' ? Number(value) : value
  if (Number.isNaN(amount)) return '—'
  return `${amount.toLocaleString('ru-RU', { minimumFractionDigits: 0, maximumFractionDigits: 2 })} ₽`
}

function formatWeekRange(week: SellerWeeklyShipmentWeek): string {
  return `${formatShortDate(week.week_start)} — ${formatShortDate(week.week_end)}`
}

function StockBadge({ level }: { level: SellerBarcodeItem['stock_level'] }) {
  return <span className={`stock-badge stock-badge--${level}`}>{STOCK_LABELS[level] ?? level}</span>
}

export function SellerCabinetPage() {
  const { marketplace } = useMarketplace()
  const isOzon = marketplace === 'ozon'
  const mpName = isOzon ? 'Ozon FBS' : 'WB FBS'
  const [data, setData] = useState<SellerCabinetResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [shipmentWeekIndex, setShipmentWeekIndex] = useState(0)

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
  }, [marketplace])

  useEffect(() => {
    load()
  }, [load])

  const shipmentWeeks = data?.weekly_shipments?.weeks ?? []
  const selectedShipmentWeek = shipmentWeeks[shipmentWeekIndex] ?? shipmentWeeks[0]
  const shipmentChartMax = useMemo(
    () => Math.max(...(selectedShipmentWeek?.days.map((item) => item.orders) ?? [0]), 1),
    [selectedShipmentWeek],
  )
  const stages = data?.stages ?? data?.wb_stages

  useEffect(() => {
    setShipmentWeekIndex(0)
  }, [data?.weekly_shipments, marketplace])

  const summary = data?.summary

  return (
    <>
      <header className="topbar">
        <div>
          <h1>Кабинет селлера</h1>
          <p>
            {data?.seller.company_name ?? `${mpName} · остатки на фулфилменте`}
            {isOzon ? ' · Seller API Ozon' : ' · Statistics API WB'}
          </p>
        </div>
        <button type="button" className="btn btn--ghost" onClick={load} disabled={loading} {...uiHint('Обновить остатки, заказы и статистику отгрузок.')}>
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
              hint={`${mpName} · календарный день (МСК)`}
              tone="blue"
              trend={summary.orders_day}
              trendLabel="к вчера"
            />
            <StatCard
              label="За неделю"
              value={summary.orders_week.current}
              hint={`${mpName} · календарная неделя пн–вс`}
              tone="purple"
              trend={summary.orders_week}
              trendLabel="к прошлой неделе"
            />
            <StatCard
              label="За месяц"
              value={summary.orders_month.current}
              hint={`${mpName} · с 1-го числа (МСК)`}
              tone="orange"
              trend={summary.orders_month}
              trendLabel="к прошлому месяцу"
            />
            <StatCard label="Остаток (шт.)" value={summary.total_stock} hint={`${summary.sku_count} SKU на складе`} tone="green" />
          </section>

          {stages && (
            <section className="stats-grid stats-grid--stages">
              <StatCard label="Новые" value={stages.new} hint="Как в сборке FBS" tone="red" />
              <StatCard label="На сборке" value={stages.in_picking} hint="Как в сборке FBS" tone="orange" />
              <StatCard label="В доставке" value={stages.in_delivery} hint="Как в сборке FBS" tone="blue" />
            </section>
          )}

          {selectedShipmentWeek && shipmentWeeks.length > 0 && (
            <section className="panel seller-weekly-shipments">
              <div className="seller-weekly-shipments__head">
                <div>
                  <h2 className="section-title">
                    {isOzon ? 'Отгрузки Ozon FBS' : 'Отгрузки на склад WB'}
                  </h2>
                  <p className="seller-weekly-shipments__hint">
                    Календарная неделя {formatWeekRange(selectedShipmentWeek)} (МСК).
                    {isOzon
                      ? ' Считаются отправления, переданные к отгрузке через CRM (ship). Сумма — по тарифу обработки за единицу.'
                      : ' Заказы из поставок WB (done) только с включённых FBS-складов фулфилмента, в т.ч. отгруженные вне CRM. Сумма — по тарифу обработки за единицу.'}
                    {selectedShipmentWeek.supplies_count > 0 && (
                      <> {isOzon ? 'Отгрузок' : 'Поставок'}: {selectedShipmentWeek.supplies_count}.</>
                    )}
                  </p>
                </div>
                <div className="seller-weekly-shipments__total">
                  <span className="seller-weekly-shipments__total-label">Итого за неделю</span>
                  <strong className="seller-weekly-shipments__total-value">
                    {formatMoney(selectedShipmentWeek.total_amount)}
                  </strong>
                  <span className="seller-weekly-shipments__total-orders">
                    {selectedShipmentWeek.total} {isOzon ? 'единиц' : 'заказов'}
                  </span>
                </div>
              </div>

              <div className="seller-weekly-shipments__nav">
                <span {...hintWrapProps('Перейти к более ранней неделе отгрузок.')}>
                  <button
                    type="button"
                    className="seller-weekly-shipments__arrow"
                    onClick={() => setShipmentWeekIndex((index) => Math.min(index + 1, shipmentWeeks.length - 1))}
                    disabled={shipmentWeekIndex >= shipmentWeeks.length - 1}
                    aria-label="Предыдущая неделя"
                  >
                    ←
                  </button>
                </span>
                <div className="seller-weekly-shipments__tabs" role="tablist" aria-label="Недели отгрузок">
                  {shipmentWeeks.map((week, index) => (
                    <button
                      key={week.week_start}
                      type="button"
                      role="tab"
                      aria-selected={index === shipmentWeekIndex}
                      className={`seller-weekly-shipments__tab${index === shipmentWeekIndex ? ' seller-weekly-shipments__tab--active' : ''}${week.is_current ? ' seller-weekly-shipments__tab--current' : ''}`}
                      onClick={() => setShipmentWeekIndex(index)}
                      {...uiHint(`Показать отгрузки за неделю ${formatWeekRange(week)}.`)}
                    >
                      {week.is_current ? 'Текущая' : formatWeekRange(week)}
                    </button>
                  ))}
                </div>
                <span {...hintWrapProps('Перейти к более поздней неделе отгрузок.')}>
                  <button
                    type="button"
                    className="seller-weekly-shipments__arrow"
                    onClick={() => setShipmentWeekIndex((index) => Math.max(index - 1, 0))}
                    disabled={shipmentWeekIndex <= 0}
                    aria-label="Следующая неделя"
                  >
                    →
                  </button>
                </span>
              </div>

              <div className="seller-chart seller-weekly-chart">
                {selectedShipmentWeek.days.map((day) => {
                  const height = Math.max(4, Math.round((day.orders / shipmentChartMax) * 140))
                  const isToday = day.date === data?.weekly_shipments.today
                  return (
                    <div key={day.date} className={`seller-chart__col${isToday ? ' seller-chart__col--today' : ''}`}>
                      <span className="seller-chart__value">{day.orders}</span>
                      <span className="seller-chart__amount">{formatMoney(day.amount)}</span>
                      <div className="seller-chart__bar" style={{ height: `${height}px` }} />
                      <span className="seller-chart__label">{day.weekday}</span>
                      <span className="seller-chart__date">{formatShortDate(day.date)}</span>
                    </div>
                  )
                })}
              </div>
            </section>
          )}
        </>
      )}

      <section className="panel seller-cabinet-table-wrap">
        <h2 className="section-title">Товары и остатки ({isOzon ? 'Ozon' : 'WB'})</h2>
        <p className="seller-cabinet-legend">
          <span className="stock-badge stock-badge--urgent">Срочно догрузить</span> — меньше 5 дней
          <span className="stock-badge stock-badge--restock">Догрузить</span> — 5–10 дней
          <span className="stock-badge stock-badge--sufficient">Норма</span> — 10–20 дней
          <span className="stock-badge stock-badge--excess">Много</span> — свыше 20 дней
        </p>

        {loading && !data && <p>Загрузка…</p>}

        {data && data.items.length === 0 && (
          <p className="seller-cabinet-empty">На складе пока нет ваших товаров {isOzon ? 'Ozon' : 'WB'}.</p>
        )}

        {data && data.items.length > 0 && (
          <div className="seller-cabinet-table-scroll">
            <table className="seller-cabinet-table">
              <thead>
                <tr>
                  <th>Фото</th>
                  <th>Товар</th>
                  <th>Размер / штрихкод</th>
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
                      <ProductPhotoThumb url={item.photo_url} alt={item.name} />
                    </td>
                    <td>
                      <Link to={`/cabinet/${encodeURIComponent(item.barcode)}`} className="seller-cabinet-link" {...uiHint('Открыть детальную карточку товара с графиком заказов.')}>
                        {item.name}
                      </Link>
                    </td>
                    <td>
                      <div className="seller-cabinet-barcode-cell">
                        {item.tech_size ? (
                          <strong className="seller-cabinet-eu-size">{item.tech_size}</strong>
                        ) : (
                          <span className="seller-cabinet-eu-size seller-cabinet-eu-size--empty">—</span>
                        )}
                        <span className="mono">{item.barcode}</span>
                      </div>
                    </td>
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
