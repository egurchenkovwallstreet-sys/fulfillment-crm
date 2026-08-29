import type { AssemblyOrder } from '../api/assembly'
import { ProductPhotoThumb } from './ProductPhotoThumb'
import { formatStickerNumber } from '../utils/stickerLabel'
import { uiHint } from '../utils/uiHint'

export type MarkingPanelKind = 'errors' | 'unbound'

type AssemblyMarkingPanelsProps = {
  errorsCount: number
  unboundCount: number
  onOpenList: (kind: MarkingPanelKind) => void
}

export function AssemblyMarkingPanels({
  errorsCount,
  unboundCount,
  onOpenList,
}: AssemblyMarkingPanelsProps) {
  return (
    <section className="assembly-marking-panels">
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
      <button
        type="button"
        className={`assembly-marking-panel${unboundCount > 0 ? ' assembly-marking-panel--alert' : ' assembly-marking-panel--ok'}`}
        onClick={() => onOpenList('unbound')}
        {...uiHint(
          'Товары с обязательной маркировкой без привязанного ЧЗ. Отсканируйте DataMatrix в поле сканирования справа.',
        )}
      >
        <span className="assembly-marking-panel__count">{unboundCount}</span>
        <span className="assembly-marking-panel__label">Без ЧЗ</span>
      </button>
    </section>
  )
}

type AssemblyMarkingListModalProps = {
  kind: MarkingPanelKind
  orders: AssemblyOrder[]
  loading?: boolean
  onClose: () => void
  onReplace?: (order: AssemblyOrder) => void
}

export function AssemblyMarkingListModal({
  kind,
  orders,
  loading = false,
  onClose,
  onReplace,
}: AssemblyMarkingListModalProps) {
  const title = kind === 'errors' ? 'Ошибки Честного знака' : 'Товары без привязки ЧЗ'
  const emptyText =
    kind === 'errors'
      ? 'Нет заказов с отклонённым ЧЗ'
      : 'Все товары с обязательной маркировкой обработаны'

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
                </li>
              )
            })}
          </ul>
        )}
        <p className="assembly-marking-modal__hint">
          Сканируйте баркод и ЧЗ в панели справа — тот же порядок, что при основной сборке.
        </p>
      </div>
    </div>
  )
}
