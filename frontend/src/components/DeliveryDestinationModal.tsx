import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError } from '../api/client'
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

const STORAGE_KEY = (sellerId: number) => `wb-delivery-shipping-v7-${sellerId}`
const POLL_INTERVAL_MS = 4000
const MAX_POLL_ATTEMPTS = 30

const DEFAULT_PREFS: DeliveryDestinationPrefs = {
  city: 'Москва и Московская область',
  shippingPointId: null,
  dateOffset: 0,
}

function readPrefs(sellerId: number): DeliveryDestinationPrefs {
  try {
    const raw = localStorage.getItem(STORAGE_KEY(sellerId))
    if (!raw) return DEFAULT_PREFS
    const parsed = JSON.parse(raw) as Partial<DeliveryDestinationPrefs>
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
  return `#${point.id} · ${city}${point.name} — ${point.address}`
}

function resolvePreferredPointId(
  points: ShippingPoint[],
  preferredId: number | null | undefined,
): number | '' {
  if (points.length === 0) return ''
  if (preferredId != null && points.some((point) => point.id === preferredId)) {
    return preferredId
  }
  return ''
}

function normalizeSearch(value: string): string {
  return value.trim().toLowerCase().replace(/ё/g, 'е')
}

function isShippingPointsLoadingError(err: unknown): boolean {
  return err instanceof ApiError && err.code === 'shipping_points_loading'
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
  const [pointsPolling, setPointsPolling] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const pollAttemptRef = useRef(0)
  const pollTimerRef = useRef<number | null>(null)

  const selectedPoint = useMemo(
    () => points.find((point) => point.id === selectedPointId) ?? null,
    [points, selectedPointId],
  )

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

  const clearPollTimer = useCallback(() => {
    if (pollTimerRef.current != null) {
      window.clearTimeout(pollTimerRef.current)
      pollTimerRef.current = null
    }
  }, [])

  const loadPoints = useCallback(
    async (options?: {
      preferredPointId?: number | null
      refresh?: boolean
      silent?: boolean
    }) => {
      const silent = options?.silent ?? false
      if (!silent) {
        setPointsLoading(true)
        setPointsError('')
      }
      try {
        const result = await fetchShippingPoints(sellerId, {
          scope: 'all_sc',
          wb_supply_id: wbSupplyId,
          refresh: options?.refresh,
        })
        const loaded = result.shipping_points_sc ?? result.shipping_points ?? []
        setCity(result.city || 'Москва и Московская область')
        setPoints(loaded)
        pollAttemptRef.current = 0
        setPointsPolling(false)
        clearPollTimer()

        if (loaded.length === 0) {
          setPointsError('WB не вернул пункты отгрузки по Москве и МО')
          setSelectedPointId('')
          return false
        }

        setSelectedPointId((current) => {
          if (current !== '' && loaded.some((point) => point.id === current)) {
            return current
          }
          return resolvePreferredPointId(
            loaded,
            options?.preferredPointId ?? saved.shippingPointId,
          )
        })
        setPointsError('')
        return true
      } catch (err) {
        if (isShippingPointsLoadingError(err)) {
          setPoints([])
          setSelectedPointId('')
          setPointsPolling(true)
          setPointsError(
            'Список СЦ загружается в фоне — CRM обновит его автоматически…',
          )
          return false
        }
        setPoints([])
        setSelectedPointId('')
        setPointsPolling(false)
        pollAttemptRef.current = 0
        clearPollTimer()
        setPointsError(err instanceof Error ? err.message : 'Ошибка загрузки пунктов отгрузки')
        return false
      } finally {
        if (!silent) {
          setPointsLoading(false)
        }
      }
    },
    [sellerId, wbSupplyId, saved.shippingPointId, clearPollTimer],
  )

  useEffect(() => {
    void loadPoints({ preferredPointId: saved.shippingPointId })
    return () => {
      clearPollTimer()
    }
  }, [loadPoints, saved.shippingPointId, clearPollTimer])

  useEffect(() => {
    if (!pointsPolling || pointsLoading) return

    if (pollAttemptRef.current >= MAX_POLL_ATTEMPTS) {
      setPointsPolling(false)
      setPointsError(
        'Список СЦ не загрузился — нажмите «Обновить список» или подождите минуту после «На сборку».',
      )
      return
    }

    pollTimerRef.current = window.setTimeout(() => {
      pollAttemptRef.current += 1
      const forceRefresh = pollAttemptRef.current >= 8
      void loadPoints({
        preferredPointId: saved.shippingPointId,
        refresh: forceRefresh,
        silent: true,
      })
    }, POLL_INTERVAL_MS)

    return () => {
      clearPollTimer()
    }
  }, [pointsPolling, pointsLoading, loadPoints, saved.shippingPointId, clearPollTimer])

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
          Список СЦ загружается в фоне после «На сборку». Москва и МО — {points.length}.
          Выберите пункт (#ID в строке) — пропуск оформится строго на него.
        </p>

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
            СЦ / склад
            {visiblePoints.length !== points.length
              ? ` — найдено ${visiblePoints.length} из ${points.length}`
              : points.length > 0
                ? ` — ${points.length}`
                : ''}
          </span>
          <div
            className="delivery-destination-modal__points"
            role="listbox"
            aria-label="СЦ / склад"
          >
            {pointsLoading ? (
              <p className="delivery-destination-modal__points-empty">Загрузка пунктов…</p>
            ) : points.length === 0 ? (
              <p className="delivery-destination-modal__points-empty">
                {pointsPolling ? 'Список СЦ подгружается в фоне…' : '— нет СЦ в этом регионе —'}
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

        {selectedPoint ? (
          <p className="delivery-destination-modal__hint delivery-destination-modal__selected">
            Пропуск будет оформлен на: <strong>{formatPointLabel(selectedPoint)}</strong>
          </p>
        ) : null}

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
            className="btn btn--ghost"
            disabled={loading || pointsLoading}
            onClick={() => void loadPoints({ refresh: true, preferredPointId: selectedPointId || saved.shippingPointId })}
          >
            Обновить список
          </button>
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
