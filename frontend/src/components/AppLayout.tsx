import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { useMarketplace } from '../context/MarketplaceContext'
import { ROLE_LABELS } from '../types/auth'
import { uiHint } from '../utils/uiHint'
import '../App.css'

const SIDEBAR_NAV: Array<{
  to: string
  label: string
  hint: string
  end?: boolean
  className?: string
  roles: Array<'admin' | 'manager' | 'seller'>
}> = [
  {
    to: '/',
    label: 'Дашборд',
    hint: 'Сводка заказов и остатков по выбранному маркетплейсу',
    end: true,
    roles: ['admin', 'manager', 'seller'],
  },
  {
    to: '/warehouse',
    label: 'Склад',
    hint: 'Остатки CRM, перенос между FBS-складами WB, выгрузка на маркетплейс',
    roles: ['admin', 'manager'],
  },
  {
    to: '/inventory',
    label: 'Инвентаризация',
    hint: 'Сверка фактического остатка на полке с CRM и ЛК WB/Ozon',
    className: 'sidebar__link--inventory',
    roles: ['admin', 'manager'],
  },
  {
    to: '/intake',
    label: 'Приёмка',
    hint: 'Приём товара: баркод → ячейка → остаток CRM и WB',
    roles: ['admin', 'manager'],
  },
  {
    to: '/intake-xl',
    label: 'Приёмка в XL',
    hint: 'Массовая приёмка по Excel-файлу',
    className: 'sidebar__link--xl',
    roles: ['admin', 'manager'],
  },
  {
    to: '/intake-article',
    label: 'Приёмка по артикулам',
    hint: 'Приёмка по артикулу и цвету с ячейками и выгрузкой на MP',
    roles: ['admin', 'manager'],
  },
  {
    to: '/cells',
    label: 'Ячейки',
    hint: 'Просмотр и печать этикеток ячеек хранения',
    roles: ['admin', 'manager'],
  },
  {
    to: '/assembly',
    label: 'Сборка FBS',
    hint: 'Подбор, скан заказов, ЧЗ, поставки и отправка в доставку',
    roles: ['admin', 'manager'],
  },
  {
    to: '/print-agent',
    label: 'Агент печати',
    hint: 'Установка расширения Chrome для печати этикеток на Xprinter',
    roles: ['admin', 'manager'],
  },
  {
    to: '/owner',
    label: 'Кабинет владельца',
    hint: 'Селлеры, сотрудники, тарифы и биллинг',
    roles: ['admin'],
  },
  {
    to: '/cabinet',
    label: 'Мой кабинет',
    hint: 'Ваши заказы, остатки и отгрузки',
    roles: ['seller'],
  },
]

export function AppLayout() {
  const { user, logout, isAdmin, isManager, isSeller } = useAuth()
  const { marketplace, setMarketplace, showSwitcher } = useMarketplace()

  if (!user) return null

  const roleLabel = ROLE_LABELS[user.role]
  const mpLabel = marketplace === 'ozon' ? 'Ozon FBS' : 'Wildberries FBS'

  const canSee = (roles: typeof SIDEBAR_NAV[number]['roles']) =>
    (roles.includes('admin') && isAdmin) ||
    (roles.includes('manager') && isManager) ||
    (roles.includes('seller') && isSeller)

  return (
    <div className={`layout layout--${marketplace}`} data-marketplace={marketplace}>
      <aside className="sidebar">
        <div className="sidebar__brand">
          <span className="sidebar__logo">FF</span>
          <div>
            <strong>Fulfillment CRM</strong>
            <small>WMS · {mpLabel}</small>
          </div>
        </div>
        {showSwitcher && (
          <div className="mp-switcher" role="tablist" aria-label="Маркетплейс">
            <button
              type="button"
              role="tab"
              aria-selected={marketplace === 'wb'}
              className={`mp-switcher__btn${marketplace === 'wb' ? ' mp-switcher__btn--active' : ''}`}
              onClick={() => setMarketplace('wb')}
              {...uiHint('Работа с Wildberries FBS: заказы, склады, сборка')}
            >
              WB
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={marketplace === 'ozon'}
              className={`mp-switcher__btn${marketplace === 'ozon' ? ' mp-switcher__btn--active' : ''}`}
              onClick={() => setMarketplace('ozon')}
              {...uiHint('Работа с Ozon FBS: отправления, склады, сборка')}
            >
              Ozon
            </button>
          </div>
        )}
        <nav className="sidebar__nav">
          {SIDEBAR_NAV.filter((item) => canSee(item.roles)).map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `sidebar__link${item.className ? ` ${item.className}` : ''}${isActive ? ' sidebar__link--active' : ''}`
              }
              {...uiHint(item.hint)}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar__footer">
          <div className="sidebar__user">
            <strong>{user.username}</strong>
            <span>{roleLabel}</span>
            {user.fulfillment_name && <small>{user.fulfillment_name}</small>}
          </div>
          <button
            type="button"
            className="btn btn--ghost"
            onClick={logout}
            {...uiHint('Выйти из учётной записи CRM')}
          >
            Выйти
          </button>
        </div>
      </aside>
      <div className="main">
        <Outlet key={marketplace} />
      </div>
    </div>
  )
}
