import type { InventoryWarehouseLine } from '../api/warehouse'
import './StockBalanceModal.css'

export type StockBalanceModalData = {
  barcode: string
  cellNumber?: string | null
  verified: boolean
  restockRequired: boolean
  message: string
  crmQuantityBefore: number
  crmQuantityAfter: number
  reservedNewOrders: number
  wbQuantityBefore?: number | null
  wbQuantityTarget: number
  wbQuantityActual?: number | null
  intakeQuantity?: number
  physicalQuantity?: number
  warehouseName?: string
  warehouses?: InventoryWarehouseLine[]
}

type StockBalanceModalProps = {
  data: StockBalanceModalData
  loading?: boolean
  onConfirm: () => void | Promise<void>
}

function modalVariant(data: StockBalanceModalData): 'ok' | 'warning' | 'error' {
  if (!data.verified) return 'error'
  if (data.restockRequired) return 'warning'
  return 'ok'
}

function modalTitle(data: StockBalanceModalData): string {
  if (!data.verified) return 'Проверьте остатки'
  if (data.restockRequired) return 'Сохранено — нужна догрузка'
  return 'Сохранено — сверка OK'
}

export function StockBalanceModal({ data, loading = false, onConfirm }: StockBalanceModalProps) {
  const variant = modalVariant(data)

  return (
    <div className="stock-balance-modal-backdrop" role="dialog" aria-modal="true">
      <div className={`stock-balance-modal stock-balance-modal--${variant}`}>
        <h2>{modalTitle(data)}</h2>
        <p className="stock-balance-modal__message">{data.message}</p>
        <p className="stock-balance-modal__barcode">
          Баркод <code>{data.barcode}</code>
          {data.cellNumber ? <> · ячейка №{data.cellNumber}</> : null}
          {data.warehouseName ? <> · {data.warehouseName}</> : null}
        </p>

        <table className="stock-balance-modal__table">
          <tbody>
            {data.physicalQuantity != null && (
              <tr>
                <th>Насчитано на полке</th>
                <td>{data.physicalQuantity} шт.</td>
              </tr>
            )}
            {data.intakeQuantity != null && data.intakeQuantity > 0 && (
              <tr>
                <th>Принято сейчас</th>
                <td>+{data.intakeQuantity} шт.</td>
              </tr>
            )}
            <tr>
              <th>CRM</th>
              <td>{data.crmQuantityBefore} → <strong>{data.crmQuantityAfter}</strong> шт.</td>
            </tr>
            <tr>
              <th>«Новые»</th>
              <td>{data.reservedNewOrders} шт.</td>
            </tr>
            <tr>
              <th>ЛК WB (цель)</th>
              <td><strong>{data.wbQuantityTarget}</strong> шт.</td>
            </tr>
            {data.wbQuantityBefore != null && (
              <tr>
                <th>ЛК WB (было)</th>
                <td>{data.wbQuantityBefore} шт.</td>
              </tr>
            )}
            {data.wbQuantityActual != null && (
              <tr>
                <th>ЛК WB (факт)</th>
                <td className={!data.verified ? 'stock-balance-modal__diff' : undefined}>
                  {data.wbQuantityActual} шт.
                </td>
              </tr>
            )}
          </tbody>
        </table>

        {data.warehouses && data.warehouses.length > 0 && (
          <table className="stock-balance-modal__table stock-balance-modal__table--warehouses">
            <thead>
              <tr>
                <th>Склад FBS</th>
                <th>Отправили</th>
                <th>В ЛК WB</th>
              </tr>
            </thead>
            <tbody>
              {data.warehouses.map((row) => (
                <tr key={row.warehouse_id}>
                  <td>{row.warehouse_name}</td>
                  <td>{row.sent_amount}</td>
                  <td className={row.difference !== 0 ? 'stock-balance-modal__diff' : undefined}>
                    {row.wb_actual}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {!data.verified && (
          <p className="stock-balance-modal__hint">
            Сверка с ЛК WB не совпала. Проверьте склад и нажмите «Готово» — остатки будут перезаписаны.
          </p>
        )}

        <button
          type="button"
          className="btn btn--primary stock-balance-modal__close"
          disabled={loading}
          onClick={() => void onConfirm()}
        >
          {loading ? 'Сохранение…' : 'Готово'}
        </button>
      </div>
    </div>
  )
}
