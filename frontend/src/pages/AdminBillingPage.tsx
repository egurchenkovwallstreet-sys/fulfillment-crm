import { useCallback, useEffect, useMemo, useState } from 'react'
import { fetchAdminBilling, type AdminBillingSellerRow } from '../api/sellerAdmin'
import { formatMoney, WeeklyShipmentsPanel } from '../components/WeeklyShipmentsPanel'
import '../pages/SellerCabinetPage.css'
import './AdminBillingPage.css'

export function AdminBillingPage() {
  const [data, setData] = useState<Awaited<ReturnType<typeof fetchAdminBilling>> | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [weekIndex, setWeekIndex] = useState(0)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setData(await fetchAdminBilling())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка загрузки')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const sellerRows = useMemo(() => {
    if (!data) return []
    return data.sellers
      .map((row) => {
        const week = row.weekly_shipments?.weeks[weekIndex]
        return {
          ...row,
          weekOrders: week?.total ?? 0,
          weekAmount: week?.total_amount ?? '0',
          weekSupplies: week?.supplies_count ?? 0,
        }
      })
      .sort((a, b) => Number(b.weekAmount) - Number(a.weekAmount))
  }, [data, weekIndex])

  const weekTotals = useMemo(() => {
    const ok = sellerRows.filter((row) => !row.error && row.weekly_shipments)
    return {
      sellers: ok.length,
      orders: ok.reduce((sum, row) => sum + row.weekOrders, 0),
      amount: ok.reduce((sum, row) => sum + Number(row.weekAmount), 0),
    }
  }, [sellerRows])

  return (
    <>
      <header className="topbar">
        <div>
          <h1>Статистика отгрузок</h1>
          <p>Все селлеры · отгрузки на склад WB · суммы по тарифам</p>
        </div>
        <button type="button" className="btn btn--ghost" onClick={load} disabled={loading}>
          {loading ? 'Обновление…' : 'Обновить'}
        </button>
      </header>

      {error && <div className="dashboard-sync-msg dashboard-sync-msg--error">{error}</div>}
      {loading && !data && <p>Загрузка… (запросы к WB могут занять 1–2 минуты)</p>}

      {data?.combined && (
        <WeeklyShipmentsPanel
          data={data.combined}
          title="Все селлеры — итого"
          weekIndex={weekIndex}
          onWeekIndexChange={setWeekIndex}
        />
      )}

      {data && (
        <section className="panel admin-billing-sellers">
          <div className="admin-billing-sellers__head">
            <h2 className="section-title">По селлерам</h2>
            <p className="admin-billing-sellers__meta">
              {weekTotals.sellers} селлеров · {weekTotals.orders} заказов · {formatMoney(weekTotals.amount)}
            </p>
          </div>

          <div className="sellers-table-scroll">
            <table className="sellers-table admin-billing-table">
              <thead>
                <tr>
                  <th>Селлер</th>
                  <th>Заказов</th>
                  <th>Сумма</th>
                  <th>Поставок</th>
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
  }
}) {
  if (row.error) {
    return (
      <tr>
        <td><strong>{row.company_name}</strong></td>
        <td colSpan={3}>—</td>
        <td><span className="sellers-tag sellers-tag--warn">{row.error}</span></td>
      </tr>
    )
  }

  return (
    <tr>
      <td><strong>{row.company_name}</strong></td>
      <td>{row.weekOrders}</td>
      <td>{formatMoney(row.weekAmount)}</td>
      <td>{row.weekSupplies}</td>
      <td><span className="sellers-tag sellers-tag--ok">OK</span></td>
    </tr>
  )
}
