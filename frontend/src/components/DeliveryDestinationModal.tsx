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

const STORAGE_KEY = (sellerId: number) => `wb-delivery-shipping-v1-${sellerId}`

const DEFAULT_PREFS: DeliveryDestinationPrefs = {
  city: 'Москва',
  shippingPointId: null,
  dateOffset: 0,
}

function readPrefs(sellerId: number): DeliveryDestinationPrefs {
  try {
    const raw = localStorage.getItem(STORAGE_KEY(sellerId))
    if (!raw) return DEFAULT_PREFS
    const parsed = JSON.parse(raw) as Partial<DeliveryDestinationPrefs>
    return {
      city: parsed.city?.trim() || DEFAULT_PREFS.city,
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

function officeTypeLabel(type: ShippingPoint['officeType']): string {
  if (type === 'sc') return 'СЦ'
  if (type === 'pp') return 'ПВЗ'
  return 'Склад'
}

function formatPointLabel(point: ShippingPoint): string {
  return `${point.name} (${officeTypeLabel(point.officeType)}) — ${point.address}`
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
  const [cityDraft, setCityDraft] = useState(saved.city)
  const [dateOffset, setDateOffset] = useState<DeliveryDateOffset>(saved.dateOffset)
  const [selectedPointId, setSelectedPointId] = useState<number | ''>(
    saved.shippingPointId ?? '',
  )
  const [points, setPoints] = useState<ShippingPoint[]>([])
  const [pointsLoading, setPointsLoading] = useState(false)
  const [pointsError, setPointsError] = useState('')

  const loadPoints = useCallback(
    async (nextCity: string) => {
      const trimmed = nextCity.trim()
      if (!trimmed) {
        setPointsError('Введите город')
        setPoints([])
        return
      }
      setPointsLoading(true)
      setPointsError('')
      try {
        const result = await fetchShippingPoints(sellerId, {
          city: trimmed,
          wb_supply_id: wbSupplyId,
        })
        setCity(trimmed)
        setPoints(result.shipping_points)
        if (result.shipping_points.length === 0) {
          setPointsError('WB не вернул пункты отгрузки для этого города')
          setSelectedPointId('')
        } else if (
          saved.shippingPointId &&
          result.shipping_points.some((point) => point.id === saved.shippingPointId)
        ) {
          setSelectedPointId(saved.shippingPointId)
        } else {
          setSelectedPointId(result.shipping_points[0].id)
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
    void loadPoints(saved.city)
  }, [loadPoints, saved.city])

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

        <label className="delivery-destination-modal__field">
          <span>Город отгрузки</span>
          <div className="delivery-destination-modal__city-row">
            <input
              type="text"
              value={cityDraft}
              disabled={loading || pointsLoading}
              onChange={(e) => setCityDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  void loadPoints(cityDraft)
                }
              }}
              placeholder="Москва"
            />
            <button
              type="button"
              className="btn btn--secondary"
              disabled={loading || pointsLoading}
              onClick={() => void loadPoints(cityDraft)}
            >
              {pointsLoading ? 'Загрузка…' : 'Найти'}
            </button>
          </div>
        </label>

        <label className="delivery-destination-modal__field">
          <span>Пункт отгрузки (СЦ / ПВЗ)</span>
          <select
            value={selectedPointId}
            disabled={loading || pointsLoading || points.length === 0}
            onChange={(e) => setSelectedPointId(Number(e.target.value))}
          >
            {points.length === 0 ? (
              <option value="">— нет пунктов —</option>
            ) : (
              points.map((point) => (
                <option key={point.id} value={point.id}>
                  {formatPointLabel(point)}
                </option>
              ))
            )}
          </select>
        </label>

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
