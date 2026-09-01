import './StockTransferResultModal.css'
import { uiHint } from '../utils/uiHint'
import type { StockTransferResultView } from '../api/warehouseHub'

type Props = {
  result: StockTransferResultView
  onClose: () => void
}

function formatWasNow(before: number, after: number) {
  return `${before} → ${after}`
}

export function StockTransferResultModal({ result, onClose }: Props) {
  const isSuccess = result.ok

  return (
    <div
      className={`stock-transfer-result-backdrop${isSuccess ? ' stock-transfer-result-backdrop--ok' : ' stock-transfer-result-backdrop--fail'}`}
      role="presentation"
      onClick={onClose}
    >
      <div
        className={`stock-transfer-result${isSuccess ? ' stock-transfer-result--ok' : ' stock-transfer-result--fail'}`}
        role="alertdialog"
        aria-labelledby="stock-transfer-result-title"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="stock-transfer-result-title">
          {isSuccess ? 'Перенос выполнен' : 'Перенос завершён с проблемами'}
        </h2>
        <p className="stock-transfer-result__summary">{result.summary}</p>

        {result.items.length > 0 && (
          <div className="stock-transfer-result__table-wrap">
            <table className="stock-transfer-result__table">
              <thead>
                <tr>
                  <th>Баркод</th>
                  <th>Откуда</th>
                  <th>Куда</th>
                  <th>Итого</th>
                </tr>
              </thead>
              <tbody>
                {result.items.map((item) => (
                  <tr key={item.barcode} className={item.ok ? '' : 'stock-transfer-result__row--bad'}>
                    <td><code>{item.barcode}</code></td>
                    <td>
                      {item.from_warehouse.name}: {formatWasNow(item.from_warehouse.before, item.from_warehouse.after)}
                    </td>
                    <td>
                      {item.to_warehouse.name}: {formatWasNow(item.to_warehouse.before, item.to_warehouse.after)}
                    </td>
                    <td>{formatWasNow(item.total_before, item.total_after)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {result.errors.length > 0 && (
          <ul className="stock-transfer-result__errors">
            {result.errors.map((row) => (
              <li key={`${row.barcode}-${row.error}`}>
                <code>{row.barcode}</code>: {row.error}
              </li>
            ))}
          </ul>
        )}

        <div className="stock-transfer-result__actions">
          <button
            type="button"
            className="btn btn--primary stock-transfer-result__ok"
            onClick={onClose}
            {...uiHint('Закрыть отчёт о переносе')}
          >
            Понятно
          </button>
        </div>
      </div>
    </div>
  )
}
