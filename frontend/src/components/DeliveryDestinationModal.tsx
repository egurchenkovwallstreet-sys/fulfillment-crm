import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  fetchShippingPoints,
  type DeliveryShippingParams,
  type ShippingPoint,
  type ShippingPointOfficeType,
} from '../api/assembly'
import './AssemblyModal.css'
import './DeliveryDestinationModal.css'

export type DeliveryDateOffset = 0 | 1 | 2
export type ShippingOfficeKind = 'sc' | 'pp'

export type DeliveryDestinationPrefs = {
  city: string
  officeKind: ShippingOfficeKind
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

const STORAGE_KEY = (sellerId: number) => `wb-delivery-shipping-v2-${sellerId}`

export const SHIPPING_CITY_OPTIONS = [
  { value: 'Москва', label: 'Москва' },
  { value: 'Московская область', label: 'Московская область' },
  { value: 'Санкт-Петербург', label: 'Санкт-Петербург' },
] as const

const DEFAULT_PREFS: DeliveryDestinationPrefs = {
  city: 'Москва',
  officeKind: 'sc',
  shippingPointId: null,
  dateOffset: 0,
}

function normalizeOfficeKind(value: unknown): ShippingOfficeKind {
  return value === 'pp' ? 'pp' : 'sc'
}

function normalizeCity(value: unknown): string {
  const trimmed = typeof value === 'string' ? value.trim() : ''
  if (SHIPPING_CITY_OPTIONS.some((option) => option.value === trimmed)) {
    return trimmed
  }
  return DEFAULT_PREFS.city
}

function readPrefs(sellerId: number): DeliveryDestinationPrefs {
  try {
    const raw = localStorage.getItem(STORAGE_KEY(sellerId))
    if (!raw) return DEFAULT_PREFS
    const parsed = JSON.parse(raw) as Partial<DeliveryDestinationPrefs>
    return {
      city: normalizeCity(parsed.city),
      officeKind: normalizeOfficeKind(parsed.officeKind),
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

function matchesOfficeKind(
  officeType: ShippingPointOfficeType,
  kind: ShippingOfficeKind,
): boolean {
  if (kind === 'sc') {
    return officeType === 'sc' || officeType === 'sw'
  }
  return officeType === 'pp'
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
  const [officeKind, setOfficeKind] = useState<ShippingOfficeKind>(saved.officeKind)
  const [dateOffset, setDateOffset] = useState<DeliveryDateOffset>(saved.dateOffset)
  const [selectedPointId, setSelectedPointId] = useState<number | ''>(
    saved.shippingPointId ?? '',
  )
  const [points, setPoints] = useState<ShippingPoint[]>([])
  const [pointsLoading, setPointsLoading] = useState(false)
  const [pointsError, setPointsError] = useState('')
  const [searchQuery, setSearchQuery] = useState('')

  const filteredPoints = useMemo(
    () => points.filter((point) => matchesOfficeKind(point.officeType, officeKind)),
    [points, officeKind],
  )

  const visiblePoints = useMemo(() => {
    const query = normalizeSearch(searchQuery)
    if (!query) return filteredPoints
    return filteredPoints.filter((point) => {
      const haystack = normalizeSearch(
        `${point.city} ${point.name} ${point.address}`,
      )
      return haystack.includes(query)
    })
  }, [filteredPoints, searchQuery])

  const loadPoints = useCallback(
    async (
      nextKind: ShippingOfficeKind,
      nextCity: string,
      preferredPointId?: number | null,
    ) => {
      setPointsLoading(true)
      setPointsError('')
      try {
        const result =
          nextKind === 'sc'
            ? await fetchShippingPoints(sellerId, {
                scope: 'all_sc',
                wb_supply_id: wbSupplyId,
              })
            : await fetchShippingPoints(sellerId, {
                city: normalizeCity(nextCity),
                wb_supply_id: wbSupplyId,
              })

        if (nextKind === 'pp') {
          setCity(normalizeCity(nextCity))
        } else {
          setCity(result.city || 'Россия (все СЦ)')
        }
        setPoints(result.shipping_points)

        const visible = result.shipping_points.filter((point) =>
          matchesOfficeKind(point.officeType, nextKind),
        )
        if (visible.length === 0) {
          const kindLabel = nextKind === 'sc' ? 'СЦ' : 'ПВЗ'
          setPointsError(`WB не вернул пункты типа «${kindLabel}»`)
          setSelectedPointId('')
        } else {
          setSelectedPointId(pickPointId(visible, preferredPointId ?? saved.shippingPointId))
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
    void loadPoints(saved.officeKind, saved.city, saved.shippingPointId)
  }, [loadPoints, saved.city, saved.officeKind, saved.shippingPointId])

  function handleCityChange(nextCity: string) {
    const normalized = normalizeCity(nextCity)
    setCity(normalized)
    setSearchQuery('')
    void loadPoints('pp', normalized, null)
  }

  function handleOfficeKindChange(nextKind: ShippingOfficeKind) {
    setOfficeKind(nextKind)
    setSearchQuery('')
    void loadPoints(nextKind, city, null)
  }

  function handleConfirm() {
    if (selectedPointId === '' || !Number.isFinite(selectedPointId)) {
      setPointsError('Выберите пункт отгрузки')
      return
    }
    const prefs: DeliveryDestinationPrefs = {
      city,
      officeKind,
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

  const officeKindLabels: Array<{ kind: ShippingOfficeKind; label: string }> = [
    { kind: 'sc', label: 'СЦ' },
    { kind: 'pp', label: 'ПВЗ' },
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

        {officeKind === 'pp' ? (
          <label className="delivery-destination-modal__field">
            <span>Город для ПВЗ</span>
            <select
              value={city}
              disabled={loading || pointsLoading}
              onChange={(e) => handleCityChange(e.target.value)}
            >
              {SHIPPING_CITY_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <p className="delivery-destination-modal__hint">
            Сортировочные центры по всей России ({filteredPoints.length}). Поиск: «липкин», «веш», «пушкино»…
          </p>
        )}

        <div className="delivery-destination-modal__field">
          <span>Тип пункта</span>
          <div className="delivery-destination-modal__type-row">
            {officeKindLabels.map(({ kind, label }) => (
              <button
                key={kind}
                type="button"
                className={`btn btn--ghost delivery-destination-modal__type${
                  officeKind === kind ? ' delivery-destination-modal__type--active' : ''
                }`}
                disabled={loading || pointsLoading}
                onClick={() => handleOfficeKindChange(kind)}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        <label className="delivery-destination-modal__field">
          <span>Поиск пункта отгрузки</span>
          <input
            type="search"
            value={searchQuery}
            disabled={loading || pointsLoading}
            placeholder="Город, название или адрес…"
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </label>

        <div className="delivery-destination-modal__field">
          <span>
            Пункт отгрузки ({officeKind === 'sc' ? 'СЦ' : 'ПВЗ'})
            {visiblePoints.length !== filteredPoints.length
              ? ` — найдено ${visiblePoints.length} из ${filteredPoints.length}`
              : filteredPoints.length > 0
                ? ` — ${filteredPoints.length}`
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
