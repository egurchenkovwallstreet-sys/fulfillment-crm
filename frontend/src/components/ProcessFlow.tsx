const steps = [
  { num: 1, title: 'Приёмка', desc: 'Скан баркода → ячейка → остаток' },
  { num: 2, title: 'Лист подбора', desc: 'Группировка заказов по ячейкам' },
  { num: 3, title: 'Сборка', desc: 'Скан заказа → печать этикетки FBS' },
  { num: 4, title: 'Честный знак', desc: 'DataMatrix → привязка к заказу' },
  { num: 5, title: 'Поставка', desc: 'ШК поставки → списание остатков' },
]

export function ProcessFlow() {
  return (
    <section className="process-flow">
      <h2 className="section-title">Процесс FBS на складе</h2>
      <div className="process-flow__track">
        {steps.map((step, index) => (
          <div key={step.num} className="process-step">
            <div className="process-step__badge">{step.num}</div>
            <div className="process-step__body">
              <strong>{step.title}</strong>
              <span>{step.desc}</span>
            </div>
            {index < steps.length - 1 && <div className="process-step__arrow" aria-hidden>→</div>}
          </div>
        ))}
      </div>
    </section>
  )
}
