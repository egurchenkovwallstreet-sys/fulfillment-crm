import { NavLink, Outlet } from 'react-router-dom'
import { uiHint } from '../../utils/uiHint'
import './OwnerLayout.css'

const NAV = [
  {
    to: '/owner',
    label: 'Обзор',
    hint: 'Краткая сводка по фулфилменту и быстрые ссылки',
    end: true as const,
  },
  {
    to: '/owner/sellers',
    label: 'Селлеры',
    hint: 'Подключение селлеров, токены WB/Ozon и склады FBS',
  },
  {
    to: '/owner/staff',
    label: 'Сотрудники',
    hint: 'Учётные записи менеджеров склада',
  },
  {
    to: '/owner/pricing',
    label: 'Ценовые группы',
    hint: 'Группы товаров и базовая стоимость обработки',
  },
  {
    to: '/owner/tariffs',
    label: 'Тарифы и габариты',
    hint: 'Тариф отгрузки и габариты для хранения по каждому баркоду',
  },
  {
    to: '/owner/billing',
    label: 'Статистика',
    hint: 'Отгрузки и суммы к оплате по селлерам и неделям',
  },
  {
    to: '/owner/product-stats',
    label: 'По товарам',
    hint: 'Сколько штук отгружено через CRM по каждому баркоду',
  },
  {
    to: '/owner/supplies',
    label: 'Поставки',
    hint: 'Отгруженные поставки WB за месяц — CRM и заказы через ЛК WB',
  },
  {
    to: '/owner/shipping-points',
    label: 'Склады WB',
    hint: 'Справочник пунктов отгрузки WB — просмотр и обновление кеша',
  },
] as const

export function OwnerLayout() {
  return (
    <div className="owner-layout">
      <nav className="owner-subnav" aria-label="Кабинет владельца">
        {NAV.map(({ to, label, hint, ...rest }) => (
          <NavLink
            key={to}
            to={to}
            end={'end' in rest ? rest.end : false}
            className={({ isActive }) => `owner-subnav__link${isActive ? ' owner-subnav__link--active' : ''}`}
            {...uiHint(hint)}
          >
            {label}
          </NavLink>
        ))}
      </nav>
      <div className="owner-content">
        <Outlet />
      </div>
    </div>
  )
}
