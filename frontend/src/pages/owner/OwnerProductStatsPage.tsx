import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  fetchCrmProductStats,
  fetchSellersManage,
  type CrmProductStatsPeriod,
  type CrmProductStatsResponse,
  type SellerManageItem,
} from '../../api/sellerAdmin'
import './OwnerLayout.css'
import './OwnerProductStatsPage.css'

type Marketplace = 'wb' | 'ozon'

const PERIODS: { id: CrmProductStatsPeriod; label: string }[] = [
  { id: 'day', label: 'Сегодня' },
  { id: 'week', label: 'Неделя' },
  { id: 'month', label: 'Месяц' },
  { id: 'all', label: 'Всё время CRM' },
  { id: 'custom', label: 'Свои даты' },
]

function formatDateLabel(value: string | null | undefined): string {
  if (!value) return '—'
  const [year, month, day] = value.split('-')
  if (!year || !month || !day) return value
  return `${day}.${month}.${year}`
}

export function OwnerProductStatsPage() {
  const [sellers, setSellers] = useState<SellerManageItem[]>([])
  const [sellerId, setSellerId] = useState<number | ''>('')
  const [marketplace, setMarketplace] = useState<Marketplace>('wb')
  const [period, setPeriod] = useState<CrmProductStatsPeriod>('all')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [barcodeQuery, setBarcodeQuery] = useState('')
  const [barcodeApplied, setBarcodeApplied] = useState('')
  const [data, setData] = useState<CrmProductStatsResponse | null>(null)
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

  const loadStats = useCallback(async () => {
    if (!sellerId) {
      setData(null)
      return
    }
    if (period === 'custom' && (!dateFrom || !dateTo)) {
      setError('Укажите дату «с» и «по»')
      return
    }
    setLoading(true)
    setError('')
    try {
      const result = await fetchCrmProductStats({
        sellerId,
        marketplace,
        period,
        dateFrom: period === 'custom' ? dateFrom : undefined,
        dateTo: period === 'custom' ? dateTo : undefined,
        barcode: barcodeApplied || undefined,
      })
      setData(result)
    } catch (err) {
      setData(null)
      setError(err instanceof Error ? err.message : 'Не удалось загрузить статистику')
    } finally {
      setLoading(false)
    }
  }, [sellerId, marketplace, period, dateFrom, dateTo, barcodeApplied])

  useEffect(() => {
    setBarcodeQuery('')
    setBarcodeApplied('')
    setData(null)
  }, [sellerId, marketplace])

  useEffect(() => {
    if (!sellerId) return
    if (period === 'custom' && (!dateFrom || !dateTo)) return
    void loadStats()
  }, [sellerId, marketplace, period, dateFrom, dateTo, barcodeApplied, loadStats])

  const periodLabel = useMemo(() => {
    if (!data) return ''
    if (data.period === 'all') return 'за весь период CRM'
    if (data.date_from && data.date_to) {
      return `с ${formatDateLabel(data.date_from)} по ${formatDateLabel(data.date_to)}`
    }
    return ''
  }, [data])

  function applyBarcodeSearch(event?: React.FormEvent) {
    event?.preventDefault()
    setBarcodeApplied(barcodeQuery.trim())
  }

  function clearBarcodeSearch() {
    setBarcodeQuery('')
    setBarcodeApplied('')
  }

  return (
    <>
      <header className="topbar">
        <div>
          <h1>Отгрузки по товарам</h1>
          <p>
            Сколько штук отгружено через CRM по каждому баркоду выбранного селлера — за весь срок работы CRM.
          </p>
        </div>
      </header>

      {error && <div className="dashboard-sync-msg dashboard-sync-msg--error">{error}</div>}

      <section className="panel owner-product-stats-panel">
        <div className="owner-product-stats-tabs" role="tablist" aria-label="Маркетплейс">
          <button
            type="button"
            role="tab"
            aria-selected={marketplace === 'wb'}
            className={`owner-product-stats-tab${marketplace === 'wb' ? ' owner-product-stats-tab--active' : ''}`}
            onClick={() => setMarketplace('wb')}
          >
            Wildberries
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={marketplace === 'ozon'}
            className={`owner-product-stats-tab${marketplace === 'ozon' ? ' owner-product-stats-tab--active' : ''}`}
            onClick={() => setMarketplace('ozon')}
          >
            Ozon
          </button>
        </div>

        <div className="owner-product-stats-toolbar">
          <label className="owner-product-stats-field">
            <span>Селлер</span>
            <select
              value={sellerId}
              onChange={(event) => setSellerId(event.target.value ? Number(event.target.value) : '')}
              disabled={loadingSellers || loading}
            >
              <option value="">Выберите селлера…</option>
              {sellers.map((seller) => (
                <option key={seller.id} value={seller.id}>
                  {seller.company_name}
                </option>
              ))}
            </select>
          </label>

          <form className="owner-product-stats-field" onSubmit={applyBarcodeSearch}>
            <span>Поиск по баркоду</span>
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              <input
                type="text"
                value={barcodeQuery}
                onChange={(event) => setBarcodeQuery(event.target.value)}
                placeholder="Часть баркода…"
                disabled={!sellerId || loading}
              />
              <button type="submit" className="btn btn--secondary" disabled={!sellerId || loading}>
                Найти
              </button>
              {(barcodeQuery || barcodeApplied) && (
                <button
                  type="button"
                  className="btn btn--ghost"
                  onClick={clearBarcodeSearch}
                  disabled={!sellerId || loading}
                >
                  Сбросить
                </button>
              )}
            </div>
          </form>
        </div>

        <div className="owner-product-stats-periods">
          {PERIODS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`btn btn--secondary${period === item.id ? ' btn--active' : ''}`}
              onClick={() => setPeriod(item.id)}
              disabled={!sellerId || loading}
            >
              {item.label}
            </button>
          ))}
        </div>

        {period === 'custom' && (
          <div className="owner-product-stats-toolbar">
            <label className="owner-product-stats-field">
              <span>С даты</span>
              <input
                type="date"
                value={dateFrom}
                onChange={(event) => setDateFrom(event.target.value)}
                disabled={!sellerId || loading}
              />
            </label>
            <label className="owner-product-stats-field">
              <span>По дату</span>
              <input
                type="date"
                value={dateTo}
                onChange={(event) => setDateTo(event.target.value)}
                disabled={!sellerId || loading}
              />
            </label>
          </div>
        )}

        {sellerId && data && (
          <div className="owner-product-stats-meta">
            <span>{data.company_name}</span>
            <span>
              Данные CRM: <strong>{formatDateLabel(data.crm_data_from)}</strong>
              {' — '}
              <strong>{formatDateLabel(data.crm_data_to)}</strong>
            </span>
            <span>
              Показано {periodLabel}: <strong>{data.total_units.toLocaleString('ru-RU')} шт.</strong>
            </span>
            <span>{data.items.length} баркод(ов)</span>
            {data.barcode_filter && (
              <span>Фильтр: <strong>{data.barcode_filter}</strong></span>
            )}
          </div>
        )}

        {!sellerId && !loadingSellers && (
          <p className="owner-tariffs-empty">Выберите селлера, чтобы увидеть статистику.</p>
        )}

        {sellerId && loading && <p>Загрузка…</p>}

        {sellerId && !loading && data && data.items.length === 0 && (
          <p className="owner-tariffs-empty">Нет отгрузок через CRM за выбранный период.</p>
        )}

        {sellerId && !loading && data && data.items.length > 0 && (
          <div className="owner-product-stats-table-wrap">
            <table className="owner-product-stats-table">
              <thead>
                <tr>
                  <th>Баркод</th>
                  <th>Товар</th>
                  <th>Размер</th>
                  <th>Артикул</th>
                  <th>Отгружено, шт.</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((item) => (
                  <tr key={item.barcode}>
                    <td><code>{item.barcode}</code></td>
                    <td>{item.name || item.barcode}</td>
                    <td>{item.tech_size || '—'}</td>
                    <td>{item.vendor_code || '—'}</td>
                    <td>{item.units.toLocaleString('ru-RU')}</td>
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
