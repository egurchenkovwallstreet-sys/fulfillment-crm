import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  fetchShippingPoints,
  type DeliveryShippingParams,
  type ShippingPoint,
  type ShippingPointKind,
} from '../api/assembly'
import './AssemblyModal.css'
import './DeliveryDestinationModal.css'

export type DeliveryDateOffset = 0 | 1 | 2

export type DeliveryDestinationPrefs = {
  city: string
  shippingPointId: number | null
  dateOffset: DeliveryDateOffset
  pointKind: ShippingPointKind
}

type Props = {
  sellerId: number
  title: string
  message: string
  wbSupplyId?: string
  initialPrefs?: DeliveryDestinationPrefs
  onConfirm: (params: DeliveryShippingParams) => void
  onClose: () => void
  loading?: boolean
}

const STORAGE_KEY = (sellerId: number) => `wb-delivery-shipping-v5-${sellerId}`

const DEFAULT_PREFS: DeliveryDestinationPrefs = {
  city: 'Москва и Московская область',
  shippingPointId: null,
  dateOffset: 0,
  pointKind: 'sc',
}

function readPrefs(sellerId: number): DeliveryDestinationPrefs {
  try {
    const raw = localStorage.getItem(STORAGE_KEY(sellerId))
    if (!raw) return DEFAULT_PREFS
    const parsed = JSON.parse(raw) as Partial<DeliveryDestinationPrefs> & {
      officeKind?: string
    }
    const legacyKind = parsed.officeKind === 'pp' ? 'pp' : 'sc'
    const pointKind: ShippingPointKind =
      parsed.pointKind === 'pp' || parsed.pointKind === 'sc'
        ? parsed.pointKind
        : legacyKind
    return {
      city: typeof parsed.city === 'string' && parsed.city.trim()
        ? parsed.city.trim()
        : DEFAULT_PREFS.city,
      shippingPointId:
        typeof parsed.shippingPointId === 'number' ? parsed.shippingPointId : null,
      dateOffset: ([0, 1, 2] as const).includes(parsed.dateOffset as DeliveryDateOffset)
        ? (parsed.dateOffset as DeliveryDateOffset)
        : 0,
      pointKind,
    }
  } catch {
    return DEFAULT_PREFS
  }
}

export function writeDeliveryPrefs(sellerId: number, prefs: DeliveryDestinationPrefs) {
  localStorage.setItem(STORAGE_KEY(sellerId), JSON.stringify(prefs))
}

function formatShippingDate(offset: DeliveryDateOffset): string {
  const date = new Date()
  date.setHours(12, 0, 0, 0)
  date.setDate(date.getDate() + offset)
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

function formatPointLabel(point: ShippingPoint): string {
  const city = point.city ? `${point.city}, ` : ''
  return `#${point.id} · ${city}${point.name} — ${point.address}`
}

function isVeshkiLipkinskoe(point: ShippingPoint): boolean {
  const haystack = normalizeSearch(`${point.city} ${point.name} ${point.address}`)
  if (!haystack.includes('липкин')) return false
  return (
    haystack.includes('веш') ||
    (haystack.includes('2') && haystack.includes('км')) ||
    haystack.includes('вешки') ||
    haystack.includes('вёшки')
  )
}

function pickPointId(
  points: ShippingPoint[],
  preferredId: number | null | undefined,
): number | '' {
  if (points.length === 0) return ''
  const veshki = points.find(isVeshkiLipkinskoe)
  if (
    preferredId != null &&
    points.some((point) => point.id === preferredId)
  ) {
    const preferred = points.find((point) => point.id === preferredId)
    if (preferred && (!veshki || !isVeshkiLipkinskoe(preferred) || preferred.id === veshki.id)) {
      return preferredId
    }
  }
  if (veshki) return veshki.id
  return points[0].id
}

function normalizeSearch(value: string): string {
  return value.trim().toLowerCase().replace(/ё/g, 'е')
}

function detectPointKind(
  pointId: number | null | undefined,
  scPoints: ShippingPoint[],
  ppPoints: ShippingPoint[],
  fallback: ShippingPointKind,
): ShippingPointKind {
  if (pointId == null) return fallback
  if (scPoints.some((point) => point.id === pointId)) return 'sc'
  if (ppPoints.some((point) => point.id === pointId)) return 'pp'
  return fallback
}

export function DeliveryDestinationModal({
  sellerId,
  title,
  message,
  wbSupplyId,
  initialPrefs,
  onConfirm,
  onClose,
  loading = false,
}: Props) {
  const saved = useMemo(
    () => initialPrefs ?? readPrefs(sellerId),
    [initialPrefs, sellerId],
  )
  const [city, setCity] = useState(saved.city)
  const [dateOffset, setDateOffset] = useState<DeliveryDateOffset>(saved.dateOffset)
  const [pointKind, setPointKind] = useState<ShippingPointKind>(saved.pointKind)
  const [selectedPointId, setSelectedPointId] = useState<number | ''>(
    saved.shippingPointId ?? '',
  )
  const [scPoints, setScPoints] = useState<ShippingPoint[]>([])
  const [ppPoints, setPpPoints] = useState<ShippingPoint[]>([])
  const [pointsLoading, setPointsLoading] = useState(false)
  const [pointsError, setPointsError] = useState('')
  const [searchQuery, setSearchQuery] = useState('')

  const activePoints = pointKind === 'pp' ? ppPoints : scPoints

  const visiblePoints = useMemo(() => {
    const query = normalizeSearch(searchQuery)
    if (!query) return activePoints
    return activePoints.filter((point) => {
      const haystack = normalizeSearch(
        `${point.city} ${point.name} ${point.address}`,
      )
      return haystack.includes(query)
    })
  }, [activePoints, searchQuery])

  const loadPoints = useCallback(
    async (preferredPointId?: number | null, preferredKind?: ShippingPointKind) => {
      setPointsLoading(true)
      setPointsError('')
      try {
        const result = await fetchShippingPoints(sellerId, {
          scope: 'all_sc',
          wb_supply_id: wbSupplyId,
        })
        const loadedSc = result.shipping_points_sc ?? result.shipping_points
        const loadedPp = result.shipping_points_pp ?? []
        setCity(result.city || 'Москва и Московская область')
        setScPoints(loadedSc)
        setPpPoints(loadedPp)

        if (loadedSc.length === 0 && loadedPp.length === 0) {
          setPointsError('WB не вернул пункты отгрузки по Москве и МО')
          setSelectedPointId('')
          return
        }

        const kind = detectPointKind(
          preferredPointId ?? saved.shippingPointId,
          loadedSc,
          loadedPp,
          preferredKind ?? saved.pointKind,
        )
        setPointKind(kind)
        const pool = kind === 'pp' ? loadedPp : loadedSc
        if (pool.length === 0) {
          const fallbackKind: ShippingPointKind = kind === 'pp' ? 'sc' : 'pp'
          const fallbackPool = fallbackKind === 'pp' ? loadedPp : loadedSc
          if (fallbackPool.length > 0) {
            setPointKind(fallbackKind)
            setSelectedPointId(
              pickPointId(fallbackPool, preferredPointId ?? saved.shippingPointId),
            )
          } else {
            setSelectedPointId('')
          }
        } else {
          setSelectedPointId(
            pickPointId(pool, preferredPointId ?? saved.shippingPointId),
          )
        }
        setPointsError('')
      } catch (err) {
        setScPoints([])
        setPpPoints([])
        setSelectedPointId('')
        setPointsError(err instanceof Error ? err.message : 'Ошибка загрузки пунктов отгрузки')
      } finally {
        setPointsLoading(false)
      }
    },
    [sellerId, wbSupplyId, saved.shippingPointId, saved.pointKind],
  )

  useEffect(() => {
    void loadPoints(saved.shippingPointId, saved.pointKind)
  }, [loadPoints, saved.pointKind, saved.shippingPointId])

  function switchPointKind(nextKind: ShippingPointKind) {
    if (nextKind === pointKind) return
    setPointKind(nextKind)
    setSearchQuery('')
    const pool = nextKind === 'pp' ? ppPoints : scPoints
    setSelectedPointId(pickPointId(pool, selectedPointId === '' ? null : selectedPointId))
  }

  function handleConfirm() {
    if (selectedPointId === '' || !Number.isFinite(selectedPointId)) {
      setPointsError('Выберите пункт отгрузки')
      return
    }
    const prefs: DeliveryDestinationPrefs = {
      city,
      shippingPointId: selectedPointId,
      dateOffset,
      pointKind,
    }
    writeDeliveryPrefs(sellerId, prefs)
    onConfirm({
      shipping_point_id: selectedPointId,
      shipping_date: formatShippingDate(dateOffset),
      shipping_type: 'selfShipping',
    })
  }

  const dateLabels: Array<{ offset: DeliveryDateOffset; label: string }> = [
    { offset: 0, label: 'Сегодня' },
    { offset: 1, label: 'Завтра' },
    { offset: 2, label: 'Послезавтра' },
  ]

  const listTitle = pointKind === 'pp' ? 'ППТ' : 'СЦ / склад'

  return (
    <div className="assembly-modal-backdrop" role="presentation" onClick={onClose}>
      <div
        className="assembly-modal delivery-destination-modal"
        role="dialog"
        aria-labelledby="delivery-destination-title"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="delivery-destination-title">{title}</h2>
        <p className="assembly-modal__message delivery-destination-modal__message">{message}</p>

        <p className="delivery-destination-modal__hint">
          Москва и Московская область: СЦ/склады (МГТ и КГТ) — {scPoints.length}, ППТ — {ppPoints.length}.
          Поиск: «липкин», «веш», «внуков», «пушкино»…
        </p>

        <div className="delivery-destination-modal__field">
          <span>Тип пункта отгрузки</span>
          <div className="delivery-destination-modal__type-row">
            <button
              type="button"
              className={`btn btn--ghost delivery-destination-modal__type${
                pointKind === 'sc' ? ' delivery-destination-modal__type--active' : ''
              }`}
              disabled={loading || pointsLoading}
              onClick={() => switchPointKind('sc')}
            >
              СЦ / склад ({scPoints.length})
            </button>
            <button
              type="button"
              className={`btn btn--ghost delivery-destination-modal__type${
                pointKind === 'pp' ? ' delivery-destination-modal__type--active' : ''
              }`}
              disabled={loading || pointsLoading}
              onClick={() => switchPointKind('pp')}
            >
              ППТ ({ppPoints.length})
            </button>
          </div>
        </div>

        <label className="delivery-destination-modal__field">
          <span>Поиск пункта отгрузки</span>
          <input
            type="search"
            value={searchQuery}
            disabled={loading || pointsLoading}
            placeholder="Город, название или адрес"
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </label>

        <div className="delivery-destination-modal__field">
          <span>
            {listTitle}
            {visiblePoints.length !== activePoints.length
              ? ` — найдено ${visiblePoints.length} из ${activePoints.length}`
              : activePoints.length > 0
                ? ` — ${activePoints.length}`
                : ''}
          </span>
          <div
            className="delivery-destination-modal__points"
            role="listbox"
            aria-label={listTitle}
          >
            {pointsLoading ? (
              <p className="delivery-destination-modal__points-empty">Загрузка пунктов…</p>
            ) : activePoints.length === 0 ? (
              <p className="delivery-destination-modal__points-empty">
                {pointKind === 'pp'
                  ? '— нет ППТ в этом регионе —'
                  : '— нет СЦ в этом регионе —'}
              </p>
            ) : visiblePoints.length === 0 ? (
              <p className="delivery-destination-modal__points-empty">— ничего не найдено —</p>
            ) : (
              visiblePoints.map((point) => (
                <button
                  key={point.id}
                  type="button"
                  role="option"
                  aria-selected={selectedPointId === point.id}
                  className={`delivery-destination-modal__point${
                    selectedPointId === point.id
                      ? ' delivery-destination-modal__point--active'
                      : ''
                  }`}
                  disabled={loading}
                  onClick={() => setSelectedPointId(point.id)}
                >
                  {formatPointLabel(point)}
                </button>
              ))
            )}
          </div>
        </div>

        <div className="delivery-destination-modal__field">
          <span>Дата отгрузки</span>
          <div className="delivery-destination-modal__dates">
            {dateLabels.map(({ offset, label }) => (
              <button
                key={offset}
                type="button"
                className={`btn btn--ghost delivery-destination-modal__date${
                  dateOffset === offset ? ' delivery-destination-modal__date--active' : ''
                }`}
                disabled={loading}
                onClick={() => setDateOffset(offset)}
              >
                {label}
                <small>{formatShippingDate(offset)}</small>
              </button>
            ))}
          </div>
        </div>

        {pointsError ? (
          <p className="delivery-destination-modal__error" role="alert">
            {pointsError}
          </p>
        ) : null}

        <div className="assembly-modal__actions">
          <button
            type="button"
            className="btn btn--primary"
            disabled={loading || pointsLoading || selectedPointId === ''}
            onClick={handleConfirm}
          >
            Подтвердить и печать QR
          </button>
          <button type="button" className="btn btn--secondary" onClick={onClose} disabled={loading}>
            Отмена
          </button>
        </div>
      </div>
    </div>
  )
}
