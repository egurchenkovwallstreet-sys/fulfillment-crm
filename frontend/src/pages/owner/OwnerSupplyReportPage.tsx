import { Fragment, useCallback, useEffect, useMemo, useState } from 'react'
import {
  fetchSellersManage,
  fetchSupplyReport,
  type SellerManageItem,
  type SupplyReportCrmOrder,
  type SupplyReportOffCrmOrder,
  type SupplyReportRow,
} from '../../api/sellerAdmin'
import { uiHint } from '../../utils/uiHint'
import './OwnerLayout.css'
import './OwnerProductStatsPage.css'
import './OwnerSupplyReportPage.css'

function currentMonthValue(): string {
  const now = new Date()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  return `${now.getFullYear()}-${month}`
}

function formatMonthLabel(value: string): string {
  const [year, month] = value.split('-')
  if (!year || !month) return value
  return `${month}.${year}`
}

function formatIsoDate(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function orderRowClass(order: SupplyReportCrmOrder | SupplyReportOffCrmOrder): string {
  if (!order.is_cancelled) return ''
  if (order.cancel_party === 'seller') return 'owner-supply-report-order--seller-cancelled'
  return 'owner-supply-report-order--cancelled'
}

export function OwnerSupplyReportPage() {
  const [sellers, setSellers] = useState<SellerManageItem[]>([])
  const [sellerId, setSellerId] = useState<number | ''>('')
  const [month, setMonth] = useState(currentMonthValue)
  const [data, setData] = useState<Awaited<ReturnType<typeof fetchSupplyReport>> | null>(null)
  const [expandedSupplyIds, setExpandedSupplyIds] = useState<Set<number>>(new Set())
  const [loadingSellers, setLoadingSellers] = useState(true)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    void (async () => {
      setLoadingSellers(true)
      try {
        const list = await fetchSellersManage()
        if (!cancelled) {
          setSellers(list.filter((seller) => seller.is_active))
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Не удалось загрузить селлеров')
        }
      } finally {
        if (!cancelled) setLoadingSellers(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const loadReport = useCallback(async (options?: { refresh?: boolean }) => {
    if (!month) {
      setError('Выберите месяц')
      return
    }
    setLoading(true)
    setError('')
    try {
      const result = await fetchSupplyReport({
        month,
        sellerId: sellerId || undefined,
        refresh: options?.refresh,
      })
      setData(result)
      setExpandedSupplyIds(new Set())
    } catch (err) {
      setData(null)
      setError(err instanceof Error ? err.message : 'Не удалось загрузить отчёт')
    } finally {
      setLoading(false)
    }
  }, [month, sellerId])

  useEffect(() => {
    void loadReport()
  }, [loadReport])

  const metaLabel = useMemo(() => {
    if (!data) return ''
    return `за ${formatMonthLabel(data.month)} (${data.month_start} — ${data.month_end})`
  }, [data])

  function toggleExpanded(supplyId: number) {
    setExpandedSupplyIds((prev) => {
      const next = new Set(prev)
      if (next.has(supplyId)) next.delete(supplyId)
      else next.add(supplyId)
      return next
    })
  }

  function renderCancelCell(order: SupplyReportCrmOrder | SupplyReportOffCrmOrder) {
    if (!order.is_cancelled) return '—'
    if (order.cancel_party === 'seller' && order.cancel_detail_label) {
      return order.cancel_detail_label
    }
    return order.cancel_detail_label || order.cancel_party_label
  }

  function renderSupplyDetails(row: SupplyReportRow) {
    return (
      <tr className="owner-supply-report-details">
        <td colSpan={8}>
          <div className="owner-supply-report-details-grid">
            <section>
              <h3>Заказы в поставке ({row.crm_orders_count})</h3>
              {row.crm_orders.length === 0 ? (
                <p className="owner-tariffs-empty">Нет заказов</p>
              ) : (
                <table className="owner-product-stats-table">
                  <thead>
                    <tr>
                      <th>Заказ WB</th>
                      <th>Баркод</th>
                      <th>Приём на СЦ WB</th>
                      <th>Статус CRM</th>
                      <th>Этап WB</th>
                      <th>Статус WB</th>
                      <th>Отмена</th>
                      <th>В доставку CRM</th>
                    </tr>
                  </thead>
                  <tbody>
                    {row.crm_orders.map((order) => (
                      <tr key={order.wb_order_id} className={orderRowClass(order)}>
                        <td>{order.wb_order_id}</td>
                        <td>{order.barcode}</td>
                        <td>{order.wb_acceptance_label}</td>
                        <td>{order.crm_status_label}</td>
                        <td>{order.wb_stage_label}</td>
                        <td>{order.wb_status_label}</td>
                        <td>{renderCancelCell(order)}</td>
                        <td>{formatIsoDate(order.in_delivery_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>
            <section>
              <h3>Вне CRM — ЛК WB ({row.off_crm_orders_count})</h3>
              {row.off_crm_orders.length === 0 ? (
                <p className="owner-tariffs-empty">Нет заказов вне CRM</p>
              ) : (
                <table className="owner-product-stats-table">
                  <thead>
                    <tr>
                      <th>Заказ WB</th>
                      <th>Баркод</th>
                      <th>Приём на СЦ WB</th>
                      <th>Этап WB</th>
                      <th>Статус WB</th>
                      <th>Отмена</th>
                      <th>Решение CRM</th>
                      <th>Отгружено WB</th>
                    </tr>
                  </thead>
                  <tbody>
                    {row.off_crm_orders.map((order) => (
                      <tr
                        key={`${order.wb_order_id}-${order.barcode}`}
                        className={orderRowClass(order)}
                      >
                        <td>{order.wb_order_id}</td>
                        <td>{order.barcode}</td>
                        <td>{order.wb_acceptance_label}</td>
                        <td>{order.wb_stage_label}</td>
                        <td>{order.wb_status_label}</td>
                        <td>{renderCancelCell(order)}</td>
                        <td>{order.resolution_status_label}</td>
                        <td>{formatIsoDate(order.shipped_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>
          </div>
        </td>
      </tr>
    )
  }

  return (
    <>
      <header className="topbar">
        <div>
          <h1>Поставки WB</h1>
          <p>Отгруженные поставки всех селлеров за месяц — приём на СЦ, статусы и отмены</p>
        </div>
      </header>

      <section className="panel owner-product-stats-panel">
        <div className="owner-product-stats-toolbar">
          <label className="owner-product-stats-field">
            <span>Месяц</span>
            <input
              type="month"
              value={month}
              onChange={(event) => setMonth(event.target.value)}
              disabled={loading}
            />
          </label>
          <label className="owner-product-stats-field">
            <span>Селлер</span>
            <select
              value={sellerId}
              onChange={(event) => setSellerId(event.target.value ? Number(event.target.value) : '')}
              disabled={loadingSellers || loading}
            >
              <option value="">Все селлеры</option>
              {sellers.map((seller) => (
                <option key={seller.id} value={seller.id}>
                  {seller.company_name}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="btn btn--ghost"
            onClick={() => void loadReport({ refresh: true })}
            disabled={loading}
            {...uiHint('Пересобрать снимок из базы CRM (без запросов к WB)')}
          >
            {loading ? 'Загрузка…' : 'Обновить'}
          </button>
        </div>

        {data && (
          <div className="owner-product-stats-meta">
            <span>
              Период: <strong>{metaLabel}</strong>
            </span>
            <span>
              Поставок: <strong>{data.totals.supplies}</strong>
            </span>
            <span>
              Заказов в поставках: <strong>{data.totals.crm_orders}</strong>
            </span>
            <span>
              Вне CRM: <strong>{data.totals.off_crm_orders}</strong>
            </span>
            {data.cached_at && (
              <span>
                Снимок: <strong>{formatIsoDate(data.cached_at)}</strong>
              </span>
            )}
          </div>
        )}

        {error && <p className="form-error">{error}</p>}

        {!loading && data && data.supplies.length === 0 && (
          <p className="owner-tariffs-empty">За выбранный месяц отгруженных поставок нет.</p>
        )}

        {data && data.supplies.length > 0 && (
          <div className="owner-product-stats-table-wrap">
            <table className="owner-product-stats-table owner-supply-report-table">
              <thead>
                <tr>
                  <th aria-label="Раскрыть" />
                  <th>Селлер</th>
                  <th>Поставка WB</th>
                  <th>Склад</th>
                  <th>Даты: CRM / ШК</th>
                  <th>Статус поставки</th>
                  <th>Заказы</th>
                  <th>Вне CRM</th>
                </tr>
              </thead>
              <tbody>
                {data.supplies.map((row) => {
                  const expanded = expandedSupplyIds.has(row.supply_id)
                  return (
                    <Fragment key={row.supply_id}>
                      <tr>
                        <td>
                          <button
                            type="button"
                            className="btn btn--ghost owner-supply-report-expand"
                            onClick={() => toggleExpanded(row.supply_id)}
                            aria-expanded={expanded}
                          >
                            {expanded ? '−' : '+'}
                          </button>
                        </td>
                        <td>{row.seller_name}</td>
                        <td>{row.wb_supply_id}</td>
                        <td>{row.warehouse_name}</td>
                        <td>{row.shipment_dates}</td>
                        <td>
                          {row.supply_status_label}
                          {row.barcode_scanned ? ' · ШК ✓' : ' · ШК —'}
                        </td>
                        <td>{row.crm_orders_count}</td>
                        <td>{row.off_crm_orders_count}</td>
                      </tr>
                      {expanded ? renderSupplyDetails(row) : null}
                    </Fragment>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  )
}
