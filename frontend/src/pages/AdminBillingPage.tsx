import { useCallback, useEffect, useMemo, useState } from 'react'
import { fetchAdminBilling, type AdminBillingSellerRow } from '../api/sellerAdmin'
import type { SellerWeeklyShipmentWeek } from '../api/sellerCabinet'
import {
  formatWeekRangeLabel,
  SellerDailyBillingTable,
} from '../components/SellerDailyBillingTable'
import { formatMoney, formatShortDate, WeeklyShipmentsPanel } from '../components/WeeklyShipmentsPanel'
import { uiHint } from '../utils/uiHint'
import '../pages/SellerCabinetPage.css'
import './AdminBillingPage.css'

type BillingMarketplace = 'wb' | 'ozon'

type EnrichedSellerRow = AdminBillingSellerRow & {
  weekOrders: number
  weekAmount: string
  weekSupplies: number
  weekStorageAmount: string
  shipmentWeek: SellerWeeklyShipmentWeek | null
  storageWeek: SellerWeeklyShipmentWeek | null | undefined
}

function shipmentWeekForRow(row: AdminBillingSellerRow, weekIndex: number): SellerWeeklyShipmentWeek | null {
  const isLiter = row.pricing_mode === 'per_liter'
  const chart = isLiter ? row.liter_shipments_chart : row.weekly_shipments
  return chart?.weeks[weekIndex] ?? null
}

export function AdminBillingPage() {
  const [marketplace, setMarketplace] = useState<BillingMarketplace>('wb')
  const [data, setData] = useState<Awaited<ReturnType<typeof fetchAdminBilling>> | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [weekIndex, setWeekIndex] = useState(0)
  const [refreshing, setRefreshing] = useState(false)
  const [expandedSellerIds, setExpandedSellerIds] = useState<Set<number>>(new Set())
  const [showDailyMatrix, setShowDailyMatrix] = useState(false)

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
    setExpandedSellerIds(new Set())
  }, [marketplace, data?.combined])

  const sellerRows = useMemo((): EnrichedSellerRow[] => {
    if (!data) return []
    return (data.sellers ?? [])
      .map((row) => {
        const shipWeek = shipmentWeekForRow(row, weekIndex)
        const storageWeek = row.liter_storage_chart?.weeks[weekIndex]
        return {
          ...row,
          weekOrders: shipWeek?.total ?? 0,
          weekAmount: shipWeek?.total_amount ?? '0',
          weekSupplies: row.weekly_shipments?.weeks[weekIndex]?.supplies_count ?? 0,
          weekStorageAmount: storageWeek?.total_amount ?? '0',
          shipmentWeek: shipWeek,
          storageWeek,
        }
      })
      .sort((a, b) => Number(b.weekAmount) + Number(b.weekStorageAmount) - Number(a.weekAmount) - Number(a.weekStorageAmount))
  }, [data, weekIndex])

  const weekTotals = useMemo(() => {
    const ok = sellerRows.filter((row) => !row.error && (row.shipmentWeek || row.storageWeek))
    const combinedWeek = data?.combined?.weeks[weekIndex]
    return {
      sellers: ok.length,
      orders: ok.reduce((sum, row) => sum + row.weekOrders, 0),
      supplies: combinedWeek?.supplies_count ?? ok.reduce((sum, row) => sum + row.weekSupplies, 0),
      amount: ok.reduce((sum, row) => sum + Number(row.weekAmount), 0),
      storage: ok.reduce((sum, row) => sum + Number(row.weekStorageAmount), 0),
    }
  }, [sellerRows, data?.combined?.weeks, weekIndex])

  const selectedWeekLabel = formatWeekRangeLabel(data?.combined?.weeks[weekIndex])
  const isOzon = marketplace === 'ozon'
  const unitsLabel = isOzon ? 'Единиц' : 'Заказов'

  function toggleSellerExpanded(sellerId: number) {
    setExpandedSellerIds((prev) => {
      const next = new Set(prev)
      if (next.has(sellerId)) next.delete(sellerId)
      else next.add(sellerId)
      return next
    })
  }

  function expandAllSellers() {
    setExpandedSellerIds(new Set(sellerRows.filter((row) => !row.error).map((row) => row.seller_id)))
  }

  return (
    <>
      <header className="topbar">
        <div>
          <h1>Статистика отгрузок</h1>
          <p>
            Все селлеры · {isOzon ? 'отгрузки Ozon FBS' : 'отгрузки на склад WB'} · по дням и суммам по тарифам
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
            <div>
              <h2 className="section-title">По селлерам</h2>
              {selectedWeekLabel && (
                <p className="admin-billing-sellers__week">Неделя {selectedWeekLabel} (МСК)</p>
              )}
            </div>
            <div className="admin-billing-sellers__actions">
              <p className="admin-billing-sellers__meta">
                {weekTotals.sellers} селлеров · {weekTotals.orders} {unitsLabel.toLowerCase()} ·{' '}
                {weekTotals.supplies} {isOzon ? 'отгрузок' : 'поставок'} ·{' '}
                отгрузка {formatMoney(weekTotals.amount)} · хранение {formatMoney(weekTotals.storage)}
              </p>
              <div className="admin-billing-sellers__buttons">
                <button
                  type="button"
                  className="btn btn--ghost admin-billing-btn--compact"
                  onClick={expandAllSellers}
                  {...uiHint('Развернуть детализацию по дням для всех селлеров')}
                >
                  Развернуть всех
                </button>
                <button
                  type="button"
                  className="btn btn--ghost admin-billing-btn--compact"
                  onClick={() => setExpandedSellerIds(new Set())}
                  {...uiHint('Свернуть детализацию по дням')}
                >
                  Свернуть
                </button>
                <button
                  type="button"
                  className={`btn btn--ghost admin-billing-btn--compact${showDailyMatrix ? ' admin-billing-btn--active' : ''}`}
                  onClick={() => setShowDailyMatrix((value) => !value)}
                  {...uiHint('Сводная таблица: все селлеры × дни недели')}
                >
                  {showDailyMatrix ? 'Скрыть сводную' : 'Сводная по дням'}
                </button>
              </div>
            </div>
          </div>

          {showDailyMatrix && (
            <div className="admin-billing-matrix-wrap">
              <DailyMatrixTable
                rows={sellerRows.filter((row) => !row.error)}
                unitsLabel={unitsLabel}
                today={data.today}
              />
            </div>
          )}

          <div className="sellers-table-scroll">
            <table className="sellers-table admin-billing-table">
              <thead>
                <tr>
                  <th aria-label="Развернуть" />
                  <th>Селлер</th>
                  <th>Режим</th>
                  <th>{unitsLabel}</th>
                  <th>{isOzon ? 'Отгрузок' : 'Поставок'}</th>
                  <th>Отгрузка</th>
                  <th>Хранение</th>
                  <th>Итого</th>
                  <th>Статус</th>
                </tr>
              </thead>
              <tbody>
                {sellerRows.map((row) => (
                  <SellerBillingRow
                    key={row.seller_id}
                    row={row}
                    unitsLabel={unitsLabel}
                    today={data.today}
                    expanded={expandedSellerIds.has(row.seller_id)}
                    onToggle={() => toggleSellerExpanded(row.seller_id)}
                  />
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
  unitsLabel,
  today,
  expanded,
  onToggle,
}: {
  row: EnrichedSellerRow
  unitsLabel: string
  today?: string
  expanded: boolean
  onToggle: () => void
}) {
  const weekTotal = Number(row.weekAmount) + Number(row.weekStorageAmount)

  if (row.error) {
    return (
      <tr>
        <td />
        <td><strong>{row.company_name}</strong></td>
        <td colSpan={6}>—</td>
        <td><span className="sellers-tag sellers-tag--warn">{row.error}</span></td>
      </tr>
    )
  }

  const modeLabel = row.pricing_mode === 'per_liter' ? 'Объём' : 'Штуки'
  const canExpand = Boolean(row.shipmentWeek || row.storageWeek)

  return (
    <>
      <tr className={expanded ? 'admin-billing-table__row--expanded' : undefined}>
        <td>
          {canExpand && (
            <button
              type="button"
              className="admin-billing-expand"
              onClick={onToggle}
              aria-expanded={expanded}
              aria-label={expanded ? 'Свернуть дни' : 'Показать по дням'}
            >
              {expanded ? '▼' : '▶'}
            </button>
          )}
        </td>
        <td><strong>{row.company_name}</strong></td>
        <td>{modeLabel}</td>
        <td>{row.weekOrders}</td>
        <td>{row.weekSupplies}</td>
        <td>{formatMoney(row.weekAmount)}</td>
        <td>{formatMoney(row.weekStorageAmount)}</td>
        <td><strong>{formatMoney(weekTotal)}</strong></td>
        <td><span className="sellers-tag sellers-tag--ok">OK</span></td>
      </tr>
      {expanded && canExpand && (
        <tr className="admin-billing-table__detail-row">
          <td colSpan={9}>
            <div className="admin-billing-daily-wrap">
              <h3 className="admin-billing-daily__title">
                {row.company_name} · по дням
                {row.shipmentWeek ? ` · ${formatWeekRangeLabel(row.shipmentWeek)}` : ''}
              </h3>
              <SellerDailyBillingTable
                shipmentWeek={row.shipmentWeek}
                storageWeek={row.storageWeek}
                unitsLabel={unitsLabel}
                today={today}
              />
            </div>
          </td>
        </tr>
      )}
    </>
  )
}

function DailyMatrixTable({
  rows,
  unitsLabel,
  today,
}: {
  rows: EnrichedSellerRow[]
  unitsLabel: string
  today?: string
}) {
  const days = rows[0]?.shipmentWeek?.days ?? rows[0]?.storageWeek?.days ?? []
  if (!days.length) return null

  return (
    <table className="admin-billing-matrix">
      <thead>
        <tr>
          <th>Селлер</th>
          {days.map((day) => (
            <th key={day.date} colSpan={2} className={today === day.date ? 'admin-billing-matrix__today' : undefined}>
              {day.weekday}
              <span className="admin-billing-matrix__date">{formatShortDate(day.date)}</span>
            </th>
          ))}
          <th colSpan={2}>Неделя</th>
        </tr>
        <tr>
          <th />
          {days.map((day) => (
            <MatrixSubHeaders key={day.date} />
          ))}
          <th>{unitsLabel}</th>
          <th>₽</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.seller_id}>
            <td><strong>{row.company_name}</strong></td>
            {days.map((day) => {
              const shipDay = row.shipmentWeek?.days.find((item) => item.date === day.date)
              const storageDay = row.storageWeek?.days.find((item) => item.date === day.date)
              const total = Number(shipDay?.amount ?? 0) + Number(storageDay?.amount ?? 0)
              return (
                <MatrixDayCells
                  key={day.date}
                  orders={shipDay?.orders ?? 0}
                  amount={total}
                  highlight={today === day.date}
                />
              )
            })}
            <td>{row.weekOrders}</td>
            <td><strong>{formatMoney(Number(row.weekAmount) + Number(row.weekStorageAmount))}</strong></td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function MatrixSubHeaders() {
  return (
    <>
      <th className="admin-billing-matrix__sub">шт</th>
      <th className="admin-billing-matrix__sub">₽</th>
    </>
  )
}

function MatrixDayCells({
  orders,
  amount,
  highlight,
}: {
  orders: number
  amount: number
  highlight?: boolean
}) {
  return (
    <>
      <td className={highlight ? 'admin-billing-matrix__today' : undefined}>{orders || '—'}</td>
      <td className={highlight ? 'admin-billing-matrix__today' : undefined}>
        {amount > 0 ? formatMoney(amount) : '—'}
      </td>
    </>
  )
}
