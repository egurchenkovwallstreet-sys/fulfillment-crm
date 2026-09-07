import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  fetchShippingPoints,
  type DeliveryShippingParams,
  type ShippingPoint,
} from '../api/assembly'
import './AssemblyModal.css'
import './DeliveryDestinationModal.css'

export type DeliveryDateOffset = 0 | 1 | 2

export type DeliveryDestinationPrefs = {
  city: string
  shippingPointId: number | null
  dateOffset: DeliveryDateOffset
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

const STORAGE_KEY = (sellerId: number) => `wb-delivery-shipping-v3-${sellerId}`

const DEFAULT_PREFS: DeliveryDestinationPrefs = {
  city: 'Москва и Московская область',
  shippingPointId: null,
  dateOffset: 0,
}

function readPrefs(sellerId: number): DeliveryDestinationPrefs {
  try {
    const raw = localStorage.getItem(STORAGE_KEY(sellerId))
    if (!raw) return DEFAULT_PREFS
    const parsed = JSON.parse(raw) as Partial<DeliveryDestinationPrefs> & {
      officeKind?: string
    }
    return {
      city: typeof parsed.city === 'string' && parsed.city.trim()
        ? parsed.city.trim()
        : DEFAULT_PREFS.city,
      shippingPointId:
        typeof parsed.shippingPointId === 'number' ? parsed.shippingPointId : null,
      dateOffset: ([0, 1, 2] as const).includes(parsed.dateOffset as DeliveryDateOffset)
        ? (parsed.dateOffset as DeliveryDateOffset)
        : 0,
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
  return `${city}${point.name} — ${point.address}`
}

function pickPointId(
  points: ShippingPoint[],
  preferredId: number | null | undefined,
): number | '' {
  if (points.length === 0) return ''
  if (
    preferredId != null &&
    points.some((point) => point.id === preferredId)
  ) {
    return preferredId
  }
  const veshki = points.find((point) => {
    const haystack = `${point.city} ${point.name} ${point.address}`.toLowerCase()
    return haystack.includes('липкин') || haystack.includes('веш')
  })
  if (veshki) return veshki.id
  return points[0].id
}

function normalizeSearch(value: string): string {
  return value.trim().toLowerCase().replace(/ё/g, 'е')
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
  const [selectedPointId, setSelectedPointId] = useState<number | ''>(
    saved.shippingPointId ?? '',
  )
  const [points, setPoints] = useState<ShippingPoint[]>([])
  const [pointsLoading, setPointsLoading] = useState(false)
  const [pointsError, setPointsError] = useState('')
  const [searchQuery, setSearchQuery] = useState('')

  const visiblePoints = useMemo(() => {
    const query = normalizeSearch(searchQuery)
    if (!query) return points
    return points.filter((point) => {
      const haystack = normalizeSearch(
        `${point.city} ${point.name} ${point.address}`,
      )
      return haystack.includes(query)
    })
  }, [points, searchQuery])

  const loadPoints = useCallback(
    async (preferredPointId?: number | null) => {
      setPointsLoading(true)
      setPointsError('')
      try {
        const result = await fetchShippingPoints(sellerId, {
          scope: 'all_sc',
          wb_supply_id: wbSupplyId,
        })
        setCity(result.city || 'Москва и Московская область')
        setPoints(result.shipping_points)
        if (result.shipping_points.length === 0) {
          setPointsError('WB не вернул пункты отгрузки (СЦ/склады) по Москве и МО')
          setSelectedPointId('')
        } else {
          setSelectedPointId(
            pickPointId(result.shipping_points, preferredPointId ?? saved.shippingPointId),
          )
          setPointsError('')
        }
      } catch (err) {
        setPoints([])
        setSelectedPointId('')
        setPointsError(err instanceof Error ? err.message : 'Ошибка загрузки пунктов отгрузки')
      } finally {
        setPointsLoading(false)
      }
    },
    [sellerId, wbSupplyId, saved.shippingPointId],
  )

  useEffect(() => {
    void loadPoints(saved.shippingPointId)
  }, [loadPoints, saved.shippingPointId])

  function handleConfirm() {
    if (selectedPointId === '' || !Number.isFinite(selectedPointId)) {
      setPointsError('Выберите пункт отгрузки')
      return
    }
    const prefs: DeliveryDestinationPrefs = {
      city,
      shippingPointId: selectedPointId,
      dateOffset,
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
          Сортировочные центры и склады WB — Москва и Московская область ({points.length}).
          Поиск: «липкин», «веш», «вешки», «пушкино»…
        </p>

        <label className="delivery-destination-modal__field">
          <span>Поиск пункта отгрузки</span>
          <input
            type="search"
            value={searchQuery}
            disabled={loading || pointsLoading}
            placeholder="Гorod, название или адрес"
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </label>

        <div className="delivery-destination-modal__field">
          <span>
            Пункт отгрузки (СЦ / склад)
            {visiblePoints.length !== points.length
              ? ` — найдено ${visiblePoints.length} из ${points.length}`
              : points.length > 0
                ? ` — ${points.length}`
                : ''}
          </span>
          <div
            className="delivery-destination-modal__points"
            role="listbox"
            aria-label="Пункты отгрузки"
          >
            {pointsLoading ? (
              <p className="delivery-destination-modal__points-empty">Загрузка пунктов…</p>
            ) : visiblePoints.length === 0 ? (
              <p className="delivery-destination-modal__points-empty">— нет пунктов —</p>
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
