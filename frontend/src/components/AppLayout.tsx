import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { useMarketplace } from '../context/MarketplaceContext'
import { ROLE_LABELS } from '../types/auth'
import '../App.css'

export function AppLayout() {
  const { user, logout, isAdmin, isManager, isSeller } = useAuth()
  const { marketplace, setMarketplace, showSwitcher } = useMarketplace()

  if (!user) return null

  const roleLabel = ROLE_LABELS[user.role]
  const mpLabel = marketplace === 'ozon' ? 'Ozon FBS' : 'Wildberries FBS'

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
            >
              WB
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={marketplace === 'ozon'}
              className={`mp-switcher__btn${marketplace === 'ozon' ? ' mp-switcher__btn--active' : ''}`}
              onClick={() => setMarketplace('ozon')}
            >
              Ozon
            </button>
          </div>
        )}
        <nav className="sidebar__nav">
          <NavLink to="/" className={({ isActive }) => `sidebar__link${isActive ? ' sidebar__link--active' : ''}`} end>
            Дашборд
          </NavLink>
          {(isAdmin || isManager) && (
            <NavLink to="/warehouse" className={({ isActive }) => `sidebar__link${isActive ? ' sidebar__link--active' : ''}`}>
              Склад
            </NavLink>
          )}
          {(isAdmin || isManager) && (
            <NavLink
              to="/inventory"
              className={({ isActive }) =>
                `sidebar__link sidebar__link--inventory${isActive ? ' sidebar__link--active' : ''}`
              }
            >
              Инвентаризация
            </NavLink>
          )}
          {(isAdmin || isManager) && (
            <NavLink to="/intake" className={({ isActive }) => `sidebar__link${isActive ? ' sidebar__link--active' : ''}`}>
              Приёмка
            </NavLink>
          )}
          {(isAdmin || isManager) && (
            <NavLink
              to="/intake-xl"
              className={({ isActive }) =>
                `sidebar__link sidebar__link--xl${isActive ? ' sidebar__link--active' : ''}`
              }
            >
              Приёмка в XL
            </NavLink>
          )}
          {(isAdmin || isManager) && (
            <NavLink
              to="/intake-article"
              className={({ isActive }) =>
                `sidebar__link${isActive ? ' sidebar__link--active' : ''}`
              }
            >
              Приёмка по артикулам
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
          {isAdmin && (
            <NavLink
              to="/owner"
              className={({ isActive }) => `sidebar__link${isActive ? ' sidebar__link--active' : ''}`}
            >
              Кабинет владельца
            </NavLink>
          )}
          {isSeller && (
            <NavLink to="/cabinet" className={({ isActive }) => `sidebar__link${isActive ? ' sidebar__link--active' : ''}`}>
              Мой кабинет
            </NavLink>
          )}
        </nav>
        <div className="sidebar__footer">
          <div className="sidebar__user">
            <strong>{user.username}</strong>
            <span>{roleLabel}</span>
            {user.fulfillment_name && <small>{user.fulfillment_name}</small>}
          </div>
          <button type="button" className="btn btn--ghost" onClick={logout}>
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
