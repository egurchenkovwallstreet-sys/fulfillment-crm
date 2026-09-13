import { useCallback, useMemo, useState } from 'react'
import {
  fetchOwnerShippingPoints,
  type OwnerShippingPoint,
  type OwnerShippingPointsResult,
} from '../../api/ownerShipping'
import { uiHint } from '../../utils/uiHint'
import './OwnerLayout.css'

type PointKind = 'sc' | 'pp'

function cargoLabel(types: number[] | undefined): string {
  if (!types?.length) return '—'
  const labels = types.map((value) => (value === 3 ? 'КГТ' : value === 1 ? 'МГТ' : String(value)))
  return labels.join(', ')
}

function formatCachedAt(value: string | null): string {
  if (!value) return '—'
  try {
    return new Date(value).toLocaleString('ru-RU')
  } catch {
    return value
  }
}

export function OwnerShippingPointsPage() {
  const [data, setData] = useState<OwnerShippingPointsResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [pointKind, setPointKind] = useState<PointKind>('sc')
  const [searchQuery, setSearchQuery] = useState('')

  const load = useCallback(async (refresh = false) => {
    setLoading(true)
    setError('')
    try {
      const result = await fetchOwnerShippingPoints({ refresh })
      setData(result)
    } catch (err) {
      setData(null)
      setError(err instanceof Error ? err.message : 'Ошибка загрузки')
    } finally {
      setLoading(false)
    }
  }, [])

  const activePoints = pointKind === 'pp' ? data?.shipping_points_pp ?? [] : data?.shipping_points_sc ?? []

  const visiblePoints = useMemo(() => {
    const query = searchQuery.trim().toLowerCase().replace(/ё/g, 'е')
    if (!query) return activePoints
    return activePoints.filter((point) => {
      const haystack = `${point.id} ${point.zone_label ?? ''} ${point.city} ${point.name} ${point.address}`
        .toLowerCase()
        .replace(/ё/g, 'е')
      return haystack.includes(query)
    })
  }, [activePoints, searchQuery])

  return (
    <>
      <header className="topbar">
        <div>
          <h1>Пункты отгрузки WB</h1>
          <p>
            Справочник СЦ, складов и ППТ по Москве и МО (~50 км). Только просмотр — заказы в доставку
            не отправляются. Кеш общий для всего фулфилмента.
          </p>
        </div>
        <div className="owner-actions-row">
          <button
            type="button"
            className="btn btn--secondary"
            disabled={loading}
            onClick={() => void load(false)}
            {...uiHint('Загрузить из общего кеша фулфилмента (быстро, если кеш уже прогрет).')}
          >
            {loading ? 'Загрузка…' : 'Загрузить'}
          </button>
          <button
            type="button"
            className="btn btn--primary"
            disabled={loading}
            onClick={() => void load(true)}
            {...uiHint('Запросить свежий список у WB и обновить общий кеш.')}
          >
            Обновить из WB
          </button>
        </div>
      </header>

      {error && <p className="owner-error">{error}</p>}

      {data && (
        <div className="owner-card owner-shipping-meta">
          <p>
            <strong>Регион:</strong> {data.city} · <strong>СЦ/склады:</strong>{' '}
            {data.shipping_points_sc.length} · <strong>ППТ:</strong> {data.shipping_points_pp.length}
          </p>
          <p>
            <strong>Токен WB:</strong> {data.reference_seller_name} (#{data.reference_seller_id}) ·{' '}
            <strong>Кеш:</strong> {data.from_cache ? 'да' : 'нет, только что загружено'} ·{' '}
            <strong>Обновлён:</strong> {formatCachedAt(data.cached_at)} · TTL {Math.round(data.cache_ttl_sec / 60)} мин
          </p>
        </div>
      )}

      <div className="owner-card">
        <div className="owner-shipping-toolbar">
          <div className="delivery-destination-modal__type-row">
            <button
              type="button"
              className={`btn btn--ghost delivery-destination-modal__type${
                pointKind === 'sc' ? ' delivery-destination-modal__type--active' : ''
              }`}
              disabled={loading}
              onClick={() => setPointKind('sc')}
            >
              СЦ / склад ({data?.shipping_points_sc.length ?? 0})
            </button>
            <button
              type="button"
              className={`btn btn--ghost delivery-destination-modal__type${
                pointKind === 'pp' ? ' delivery-destination-modal__type--active' : ''
              }`}
              disabled={loading}
              onClick={() => setPointKind('pp')}
            >
              ППТ ({data?.shipping_points_pp.length ?? 0})
            </button>
          </div>
          <input
            type="search"
            className="owner-shipping-search"
            placeholder="Поиск: ID, зона, город, название, адрес"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            disabled={loading || !data}
          />
        </div>

        {!data && !loading && !error && (
          <p className="owner-muted">Нажмите «Загрузить» или «Обновить из WB».</p>
        )}

        {data && (
          <div className="owner-table-wrap">
            <table className="owner-table owner-shipping-table">
              <thead>
                <tr>
                  <th>ID WB</th>
                  <th>Зона</th>
                  <th>Тип</th>
                  <th>Город</th>
                  <th>Название</th>
                  <th>Адрес</th>
                  <th>Груз</th>
                </tr>
              </thead>
              <tbody>
                {visiblePoints.map((point: OwnerShippingPoint) => (
                  <tr key={point.id} className={point.is_pinned ? 'owner-shipping-row--pinned' : undefined}>
                    <td>{point.id}</td>
                    <td>{point.zone_label || '—'}</td>
                    <td>{point.officeType || '—'}</td>
                    <td>{point.city || '—'}</td>
                    <td>{point.name || '—'}</td>
                    <td>{point.address || '—'}</td>
                    <td>{cargoLabel(point.cargoTypes)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {visiblePoints.length === 0 && (
              <p className="owner-muted">Ничего не найдено по текущему фильтру.</p>
            )}
          </div>
        )}
      </div>
    </>
  )
}
