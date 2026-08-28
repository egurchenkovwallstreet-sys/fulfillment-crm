import { NavLink, Outlet } from 'react-router-dom'
import './OwnerLayout.css'

const NAV = [
  { to: '/owner', label: 'Обзор', end: true },
  { to: '/owner/sellers', label: 'Селлеры' },
  { to: '/owner/staff', label: 'Сотрудники' },
  { to: '/owner/pricing', label: 'Ценовые группы' },
  { to: '/owner/billing', label: 'Статистика' },
] as const

export function OwnerLayout() {
  return (
    <div className="owner-layout">
      <nav className="owner-subnav" aria-label="Кабинет владельца">
        {NAV.map(({ to, label, ...rest }) => (
          <NavLink
            key={to}
            to={to}
            end={'end' in rest ? rest.end : false}
            className={({ isActive }) => `owner-subnav__link${isActive ? ' owner-subnav__link--active' : ''}`}
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
