import { useCallback, useEffect, useState } from 'react'
import {
  deductOffCrmShipment,
  fetchOffCrmSellerDetail,
  fetchOffCrmSummary,
  skipOffCrmShipment,
  type OffCrmSellerDetail,
  type OffCrmSellerSummary,
  type OffCrmShipmentItem,
} from '../api/offCrmShipments'
import { uiHint } from '../utils/uiHint'
import './OffCrmShipmentsModal.css'

type Props = {
  open: boolean
  onClose: () => void
  onResolved: () => void
}

function formatWhen(value: string | null) {
  if (!value) return '—'
  return new Date(value).toLocaleString('ru-RU')
}

export function OffCrmShipmentsModal({ open, onClose, onResolved }: Props) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [sellers, setSellers] = useState<OffCrmSellerSummary[]>([])
  const [pendingCount, setPendingCount] = useState(0)
  const [selectedSeller, setSelectedSeller] = useState<OffCrmSellerDetail | null>(null)
  const [busyId, setBusyId] = useState<number | null>(null)

  const loadSummary = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const data = await fetchOffCrmSummary()
      setSellers(data.sellers)
      setPendingCount(data.pending_count)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось загрузить список')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (open) {
      setSelectedSeller(null)
      loadSummary()
    }
  }, [open, loadSummary])

  async function openSeller(sellerId: number) {
    setLoading(true)
    setError('')
    try {
      const detail = await fetchOffCrmSellerDetail(sellerId)
      setSelectedSeller(detail)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось загрузить заказы')
    } finally {
      setLoading(false)
    }
  }

  async function handleAction(item: OffCrmShipmentItem, action: 'deduct' | 'skip') {
    setBusyId(item.id)
    setError('')
    try {
      if (action === 'deduct') {
        await deductOffCrmShipment(item.id)
      } else {
        await skipOffCrmShipment(item.id)
      }
      if (selectedSeller) {
        const detail = await fetchOffCrmSellerDetail(selectedSeller.seller_id)
        setSelectedSeller(detail)
      }
      await loadSummary()
      onResolved()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось выполнить действие')
    } finally {
      setBusyId(null)
    }
  }

  if (!open) return null

  return (
    <div className="off-crm-modal-backdrop" onClick={onClose} role="presentation">
      <div
        className="off-crm-modal"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="off-crm-modal-title"
      >
        <header className="off-crm-modal__header">
          <div>
            <h2 id="off-crm-modal-title">Отгрузки вне CRM</h2>
            <p>
              Заказы, отправленные через ЛК WB без сборки в CRM. Решение принимает менеджер.
            </p>
          </div>
          <button type="button" className="btn btn--ghost" onClick={onClose}>
            Закрыть
          </button>
        </header>

        {error && <div className="off-crm-modal__error">{error}</div>}

        {loading && !selectedSeller && sellers.length === 0 ? (
          <p className="off-crm-modal__muted">Загрузка…</p>
        ) : null}

        {!selectedSeller ? (
          <section>
            <p className="off-crm-modal__count">
              Ожидают решения: <strong>{pendingCount}</strong>
            </p>
            {sellers.length === 0 ? (
              <p className="off-crm-modal__muted">Нет отгрузок для проверки</p>
            ) : (
              <ul className="off-crm-seller-list">
                {sellers.map((seller) => (
                  <li key={seller.seller_id}>
                    <button
                      type="button"
                      className="off-crm-seller-list__item"
                      onClick={() => openSeller(seller.seller_id)}
                      {...uiHint('Открыть список заказов селлера')}
                    >
                      <span>{seller.seller_name}</span>
                      <span className="off-crm-seller-list__badge">{seller.pending_count}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
        ) : (
          <section>
            <button
              type="button"
              className="btn btn--ghost off-crm-modal__back"
              onClick={() => setSelectedSeller(null)}
            >
              ← К списку селлеров
            </button>
            <h3 className="off-crm-modal__seller-title">{selectedSeller.seller_name}</h3>
            {selectedSeller.items.length === 0 ? (
              <p className="off-crm-modal__muted">Нет заказов, ожидающих решения</p>
            ) : (
              <ul className="off-crm-order-list">
                {selectedSeller.items.map((item) => (
                  <li key={item.id} className="off-crm-order-list__item">
                    <div className="off-crm-order-list__meta">
                      <strong>WB #{item.wb_order_id}</strong>
                      <span>{item.warehouse_name}</span>
                      <span>Баркод: {item.barcode}</span>
                      <span>Стикер: {item.sticker_number}</span>
                      <span>Кол-во: {item.quantity} шт.</span>
                      <span>Отгружено: {formatWhen(item.shipped_at)}</span>
                    </div>
                    <div className="off-crm-order-list__actions">
                      <button
                        type="button"
                        className="btn btn--primary"
                        disabled={busyId === item.id}
                        onClick={() => handleAction(item, 'deduct')}
                        {...uiHint('Списать 1 шт. с остатков CRM')}
                      >
                        {busyId === item.id ? '…' : 'Списать с остатков в CRM'}
                      </button>
                      <button
                        type="button"
                        className="btn btn--ghost"
                        disabled={busyId === item.id}
                        onClick={() => handleAction(item, 'skip')}
                        {...uiHint('Не списывать остаток по этому заказу')}
                      >
                        Не списывать
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}
      </div>
    </div>
  )
}
