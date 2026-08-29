import { printCellLabel, type CellLabelData } from '../utils/cellLabelPrint'
import { uiHint } from '../utils/uiHint'
import './CellLabelPrompt.css'

type Props = {
  label: CellLabelData
  onClose: () => void
}

export function CellLabelPrompt({ label, onClose }: Props) {
  function handleYes() {
    printCellLabel(label, true)
    onClose()
  }

  return (
    <div className="cell-label-prompt-backdrop" role="presentation" onClick={onClose}>
      <div
        className="cell-label-prompt"
        role="dialog"
        aria-labelledby="cell-label-prompt-title"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 id="cell-label-prompt-title">Распечатать этикетку ячейки?</h3>
        <p>
          Одна наклейка 75×120: номер ячейки и маркетплейс + ИП + баркод.
          <br />
          Селлер: <strong>{label.seller_name}</strong>
          <br />
          Ячейка: <strong>№{label.cell_number}</strong>
          · {label.marketplace_label || (label.marketplace === 'ozon' ? 'OZON' : 'ВБ')}
          <br />
          Баркод: <strong>{label.barcode}</strong>
        </p>
        <div className="cell-label-prompt__actions">
          <button type="button" className="btn btn--primary" onClick={handleYes} {...uiHint('Напечатать этикетку ячейки 75×120 на Xprinter')}>
            Да
          </button>
          <button type="button" className="btn btn--secondary" onClick={onClose} {...uiHint('Пропустить печать этикетки ячейки')}>
            Нет
          </button>
        </div>
      </div>
    </div>
  )
}

export { printCellLabel, type CellLabelData }
