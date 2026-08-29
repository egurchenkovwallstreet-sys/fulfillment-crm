import { Link } from 'react-router-dom'
import { uiHint } from '../../utils/uiHint'
import './OwnerLayout.css'

const CARDS = [
  {
    to: '/owner/sellers',
    title: 'Селлеры',
    desc: 'Создание, токены WB/Ozon, тарифы, ссылки регистрации',
  },
  {
    to: '/owner/staff',
    title: 'Сотрудники',
    desc: 'Менеджеры склада — логин и пароль для работы в CRM',
  },
  {
    to: '/owner/pricing',
    title: 'Ценовые группы',
    desc: 'Группы товаров и базовая стоимость обработки',
  },
  {
    to: '/owner/billing',
    title: 'Статистика отгрузок',
    desc: 'Отгрузки WB и Ozon по всем селлерам и суммы по тарифам',
  },
] as const

export function OwnerHomePage() {
  return (
    <>
      <header className="topbar">
        <div>
          <h1>Кабинет владельца</h1>
          <p>Управление селлерами, сотрудниками, тарифами и статистикой — без Django-admin</p>
        </div>
      </header>

      <section className="owner-home-grid">
        {CARDS.map((card) => (
          <Link key={card.to} to={card.to} className="owner-home-card" {...uiHint(card.desc)}>
            <strong>{card.title}</strong>
            <span>{card.desc}</span>
          </Link>
        ))}
      </section>
    </>
  )
}
