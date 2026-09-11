import type { SellerWeeklyShipmentWeek } from '../api/sellerCabinet'
import { formatMoney, formatShortDate } from './WeeklyShipmentsPanel'

type Props = {
  shipmentWeek: SellerWeeklyShipmentWeek | null
  storageWeek: SellerWeeklyShipmentWeek | null | undefined
  unitsLabel: string
  today?: string
  compact?: boolean
}

export function SellerDailyBillingTable({
  shipmentWeek,
  storageWeek,
  unitsLabel,
  today,
  compact = false,
}: Props) {
  if (!shipmentWeek && !storageWeek) {
    return <p className="admin-billing-daily__empty">Нет данных за выбранную неделю</p>
  }

  const days = shipmentWeek?.days ?? storageWeek?.days ?? []
  const storageByDate = new Map(
    (storageWeek?.days ?? []).map((day) => [day.date, day]),
  )

  return (
    <table className={`admin-billing-daily${compact ? ' admin-billing-daily--compact' : ''}`}>
      <thead>
        <tr>
          <th>День</th>
          <th>Дата</th>
          <th>{unitsLabel}</th>
          <th>Отгрузка</th>
          <th>Хранение</th>
          <th>Итого</th>
        </tr>
      </thead>
      <tbody>
        {days.map((day) => {
          const storageDay = storageByDate.get(day.date)
          const storageAmount = Number(storageDay?.amount ?? 0)
          const shipAmount = Number(day.amount ?? 0)
          const total = shipAmount + storageAmount
          return (
            <tr
              key={day.date}
              className={today && day.date === today ? 'admin-billing-daily__row--today' : undefined}
            >
              <td>{day.weekday}</td>
              <td>{formatShortDate(day.date)}</td>
              <td>{day.orders}</td>
              <td>{formatMoney(day.amount)}</td>
              <td>{storageDay ? formatMoney(storageDay.amount) : '—'}</td>
              <td><strong>{formatMoney(total)}</strong></td>
            </tr>
          )
        })}
        {(shipmentWeek || storageWeek) && (
          <tr className="admin-billing-daily__row--total">
            <td colSpan={2}>Итого за неделю</td>
            <td>{shipmentWeek?.total ?? 0}</td>
            <td>{formatMoney(shipmentWeek?.total_amount ?? 0)}</td>
            <td>{formatMoney(storageWeek?.total_amount ?? 0)}</td>
            <td>
              <strong>
                {formatMoney(
                  Number(shipmentWeek?.total_amount ?? 0) + Number(storageWeek?.total_amount ?? 0),
                )}
              </strong>
            </td>
          </tr>
        )}
      </tbody>
    </table>
  )
}

export function formatWeekRangeLabel(week: SellerWeeklyShipmentWeek | null | undefined): string {
  if (!week) return ''
  return `${formatShortDate(week.week_start)} — ${formatShortDate(week.week_end)}`
}
