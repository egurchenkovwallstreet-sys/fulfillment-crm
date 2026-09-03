import type { AssemblyOrder } from '../api/assembly'
import { ProductPhotoThumb } from './ProductPhotoThumb'
import { formatStickerNumber } from '../utils/stickerLabel'
import { uiHint } from '../utils/uiHint'

export type AssemblyQueuePanelKind = 'in_assembly' | 'ready' | 'errors'

type AssemblyQueuePanelsProps = {
  inAssemblyCount: number
  readyCount: number
  errorsCount: number
  onOpenList: (kind: AssemblyQueuePanelKind) => void
}

export function AssemblyQueuePanels({
  inAssemblyCount,
  readyCount,
  errorsCount,
  onOpenList,
}: AssemblyQueuePanelsProps) {
  return (
    <section className="assembly-marking-panels assembly-marking-panels--triple">
      <button
        type="button"
        className={`assembly-marking-panel assembly-marking-panel--work${inAssemblyCount > 0 ? ' assembly-marking-panel--alert' : ''}`}
        onClick={() => onOpenList('in_assembly')}
        {...uiHint(
          'Заказы, где ещё не отсканирован баркод или не напечатан стикер. Нажмите — список с ячейками.',
        )}
      >
        <span className="assembly-marking-panel__count">{inAssemblyCount}</span>
        <span className="assembly-marking-panel__label">На сборке</span>
      </button>
      <button
        type="button"
        className="assembly-marking-panel assembly-marking-panel--ready"
        onClick={() => onOpenList('ready')}
        {...uiHint(
          'Собранные заказы: баркод отсканирован, стикер напечатан, ЧЗ привязан (если нужен). Готовы к доставке.',
        )}
      >
        <span className="assembly-marking-panel__count">{readyCount}</span>
        <span className="assembly-marking-panel__label">Готовые</span>
      </button>
      <button
        type="button"
        className={`assembly-marking-panel${errorsCount > 0 ? ' assembly-marking-panel--alert' : ' assembly-marking-panel--ok'}`}
        onClick={() => onOpenList('errors')}
        {...uiHint(
          'Заказы, где WB отклонил код Честного знака. Нажмите — список с ячейкой и кнопкой «Заменить товар».',
        )}
      >
        <span className="assembly-marking-panel__count">{errorsCount}</span>
        <span className="assembly-marking-panel__label">Ошибки ЧЗ</span>
      </button>
    </section>
  )
}

/** @deprecated use AssemblyQueuePanels */
export const AssemblyMarkingPanels = AssemblyQueuePanels
export type MarkingPanelKind = AssemblyQueuePanelKind

type AssemblyQueueListModalProps = {
  kind: AssemblyQueuePanelKind
  orders: AssemblyOrder[]
  loading?: boolean
  onClose: () => void
  onReplace?: (order: AssemblyOrder) => void
  onReprint?: (order: AssemblyOrder) => void
  onDeliver?: (order: AssemblyOrder) => void
}

export function AssemblyQueueListModal({
  kind,
  orders,
  loading = false,
  onClose,
  onReplace,
  onReprint,
  onDeliver,
}: AssemblyQueueListModalProps) {
  const title =
    kind === 'errors'
      ? 'Ошибки Честного знака'
      : kind === 'ready'
        ? 'Готовые к доставке'
        : 'На сборке'
  const emptyText =
    kind === 'errors'
      ? 'Нет заказов с отклонённым ЧЗ'
      : kind === 'ready'
        ? 'Пока нет собранных заказов — отсканируйте баркод в панели справа'
        : 'Все заказы собраны — новые появятся после передачи на сборку'

  return (
    <div className="assembly-marking-modal-backdrop" role="presentation" onClick={onClose}>
      <div
        className="assembly-marking-modal assembly-marking-modal--list"
        role="dialog"
        aria-labelledby="marking-list-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="assembly-marking-modal__head">
          <h2 id="marking-list-title">{title}</h2>
          <button
            type="button"
            className="btn btn--ghost btn--small"
            onClick={onClose}
            {...uiHint('Закрыть список')}
          >
            Закрыть
          </button>
        </div>
        {orders.length === 0 ? (
          <p className="assembly-marking-modal__empty">{emptyText}</p>
        ) : (
          <ul className="assembly-marking-list">
            {orders.map((order) => {
              const sticker = formatStickerNumber(order)
              const cell = (order.cell_number || '').trim()
              return (
                <li key={order.id} className="assembly-marking-list__item">
                  <ProductPhotoThumb
                    url={order.photo_url ?? ''}
                    alt={order.barcode || String(order.wb_order_id)}
                  />
                  <div className="assembly-marking-list__body">
                    <div className="assembly-marking-list__row">
                      <strong className="assembly-order-size">{order.tech_size || '—'}</strong>
                      <span>WB #{order.wb_order_id}</span>
                    </div>
                    <div className="assembly-marking-list__row">
                      <code>{order.barcode}</code>
                    </div>
                    <div className="assembly-marking-list__cell">
                      Ячейка: <strong>{cell || '—'}</strong>
                    </div>
                    {sticker && (
                      <div className="assembly-marking-list__sticker">
                        Стикер: <strong>{sticker}</strong>
                      </div>
                    )}
                    {kind === 'errors' && order.marking_verify_error && (
                      <p className="assembly-marking-list__error">{order.marking_verify_error}</p>
                    )}
                  </div>
                  <div className="assembly-marking-list__actions">
                    {kind === 'errors' && onReplace && (
                      <button
                        type="button"
                        className="btn btn--small btn--primary"
                        onClick={() => onReplace(order)}
                        disabled={loading}
                        {...uiHint('Снять заказ и подставить другой товар с тем же баркодом')}
                      >
                        Заменить товар
                      </button>
                    )}
                    {kind === 'ready' && onReprint && (
                      <button
                        type="button"
                        className="btn btn--small btn--secondary"
                        onClick={() => onReprint(order)}
                        disabled={loading}
                        {...uiHint('Повторная печать только если стикер повреждён — с подтверждением')}
                      >
                        Печать ещё раз
                      </button>
                    )}
                    {kind === 'ready' && onDeliver && (
                      <button
                        type="button"
                        className="btn btn--small btn--primary"
                        onClick={() => onDeliver(order)}
                        disabled={loading || !order.can_send_to_delivery}
                        {...uiHint('Передать заказ в доставку WB')}
                      >
                        В доставку
                      </button>
                    )}
                  </div>
                </li>
              )
            })}
          </ul>
        )}
        <p className="assembly-marking-modal__hint">
          {kind === 'in_assembly'
            ? 'Сканируйте баркод (и ЧЗ при необходимости) в панели справа — заказ сразу перейдёт в «Готовые».'
            : kind === 'ready'
              ? 'Повторная печать стикера — только через подтверждение менеджера.'
              : 'После замены товара повторите сборку: баркод → ЧЗ → печать стикера.'}
        </p>
      </div>
    </div>
  )
}

/** @deprecated use AssemblyQueueListModal */
export const AssemblyMarkingListModal = AssemblyQueueListModal
