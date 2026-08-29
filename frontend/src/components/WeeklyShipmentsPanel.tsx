import { useEffect, useMemo, useState } from 'react'
import type { SellerWeeklyShipmentWeek, SellerWeeklyShipments } from '../api/sellerCabinet'
import { uiHint, hintWrapProps } from '../utils/uiHint'

function formatShortDate(iso: string): string {
  return new Date(`${iso}T12:00:00`).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })
}

export function formatMoney(value: string | number): string {
  const amount = typeof value === 'string' ? Number(value) : value
  if (Number.isNaN(amount)) return '—'
  return `${amount.toLocaleString('ru-RU', { minimumFractionDigits: 0, maximumFractionDigits: 2 })} ₽`
}

function formatWeekRange(week: SellerWeeklyShipmentWeek): string {
  return `${formatShortDate(week.week_start)} — ${formatShortDate(week.week_end)}`
}

type Props = {
  data: SellerWeeklyShipments
  title?: string
  hint?: string
  weekIndex?: number
  onWeekIndexChange?: (index: number) => void
}

export function WeeklyShipmentsPanel({
  data,
  title = 'Отгрузки на склад WB',
  hint = 'Считаются все заказы из поставок WB (done), в т.ч. отгруженные вне CRM. Сумма — по тарифу обработки за единицу.',
  weekIndex: controlledWeekIndex,
  onWeekIndexChange,
}: Props) {
  const [internalWeekIndex, setInternalWeekIndex] = useState(0)
  const weekIndex = controlledWeekIndex ?? internalWeekIndex
  const setWeekIndex = onWeekIndexChange ?? setInternalWeekIndex

  useEffect(() => {
    setWeekIndex(0)
  }, [data, setWeekIndex])

  const weeks = data.weeks
  const selectedWeek = weeks[weekIndex] ?? weeks[0]
  const chartMax = useMemo(
    () => Math.max(...(selectedWeek?.days.map((item) => item.orders) ?? [0]), 1),
    [selectedWeek],
  )

  if (!selectedWeek) {
    return null
  }

  return (
    <section className="panel seller-weekly-shipments">
      <div className="seller-weekly-shipments__head">
        <div>
          <h2 className="section-title">{title}</h2>
          <p className="seller-weekly-shipments__hint">
            Календарная неделя {formatWeekRange(selectedWeek)} (МСК). {hint}
            {selectedWeek.supplies_count > 0 && <> Поставок: {selectedWeek.supplies_count}.</>}
          </p>
        </div>
        <div className="seller-weekly-shipments__total">
          <span className="seller-weekly-shipments__total-label">Итого за неделю</span>
          <strong className="seller-weekly-shipments__total-value">
            {formatMoney(selectedWeek.total_amount)}
          </strong>
          <span className="seller-weekly-shipments__total-orders">{selectedWeek.total} заказов</span>
        </div>
      </div>

      <div className="seller-weekly-shipments__nav">
        <span {...hintWrapProps('Показать более раннюю неделю отгрузок')}>
          <button
            type="button"
            className="seller-weekly-shipments__arrow"
            onClick={() => setWeekIndex(Math.min(weekIndex + 1, weeks.length - 1))}
            disabled={weekIndex >= weeks.length - 1}
            aria-label="Предыдущая неделя"
          >
            ←
          </button>
        </span>
        <div className="seller-weekly-shipments__tabs" role="tablist" aria-label="Недели отгрузок">
          {weeks.map((week, index) => (
            <button
              key={week.week_start}
              type="button"
              role="tab"
              aria-selected={index === weekIndex}
              className={`seller-weekly-shipments__tab${index === weekIndex ? ' seller-weekly-shipments__tab--active' : ''}${week.is_current ? ' seller-weekly-shipments__tab--current' : ''}`}
              onClick={() => setWeekIndex(index)}
              {...uiHint(`Отгрузки за неделю ${formatWeekRange(week)}`)}
            >
              {week.is_current ? 'Текущая' : formatWeekRange(week)}
            </button>
          ))}
        </div>
        <span {...hintWrapProps('Показать более позднюю неделю отгрузок')}>
          <button
            type="button"
            className="seller-weekly-shipments__arrow"
            onClick={() => setWeekIndex(Math.max(weekIndex - 1, 0))}
            disabled={weekIndex <= 0}
            aria-label="Следующая неделя"
          >
            →
          </button>
        </span>
      </div>

      <div className="seller-chart seller-weekly-chart">
        {selectedWeek.days.map((day) => {
          const height = Math.max(4, Math.round((day.orders / chartMax) * 140))
          const isToday = day.date === data.today
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
  )
}
