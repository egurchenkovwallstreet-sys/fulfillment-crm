import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { ROLE_LABELS } from '../types/auth'
import '../App.css'

export function AppLayout() {
  const { user, logout, isAdmin, isManager, isSeller } = useAuth()

  if (!user) return null

  const roleLabel = ROLE_LABELS[user.role]

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="sidebar__brand">
          <span className="sidebar__logo">FF</span>
          <div>
            <strong>Fulfillment CRM</strong>
            <small>WMS · Wildberries FBS</small>
          </div>
        </div>
        <nav className="sidebar__nav">
          <NavLink to="/" className={({ isActive }) => `sidebar__link${isActive ? ' sidebar__link--active' : ''}`} end>
            Дашборд
          </NavLink>
          {(isAdmin || isManager) && (
            <NavLink to="/intake" className={({ isActive }) => `sidebar__link${isActive ? ' sidebar__link--active' : ''}`}>
              Приёмка
            </NavLink>
          )}
          {(isAdmin || isManager) && (
            <NavLink to="/cells" className={({ isActive }) => `sidebar__link${isActive ? ' sidebar__link--active' : ''}`}>
              Ячейки
            </NavLink>
          )}
          {(isAdmin || isManager) && (
            <NavLink to="/assembly" className={({ isActive }) => `sidebar__link${isActive ? ' sidebar__link--active' : ''}`}>
              Сборка FBS
            </NavLink>
          )}
          {(isAdmin || isManager) && (
            <NavLink to="/print-agent" className={({ isActive }) => `sidebar__link${isActive ? ' sidebar__link--active' : ''}`}>
              Агент печати
            </NavLink>
          )}
          {isAdmin && <span className="sidebar__link sidebar__link--disabled">Селлеры</span>}
          {isSeller && <span className="sidebar__link sidebar__link--disabled">Мои остатки</span>}
        </nav>
        <div className="sidebar__footer">
          <div className="sidebar__user">
            <strong>{user.username}</strong>
            <span>{roleLabel}</span>
          </div>
          <button type="button" className="btn btn--ghost" onClick={logout}>
            Выйти
          </button>
        </div>
      </aside>
      <div className="main">
        <Outlet />
      </div>
    </div>
  )
}
