import { Navigate } from 'react-router-dom'
import { ProcessFlow } from '../components/ProcessFlow'
import { StatCard } from '../components/StatCard'
import { useAuth } from '../context/AuthContext'
import { ROLE_LABELS } from '../types/auth'
import '../App.css'

export function DashboardPage() {
  const { user, logout, isAdmin, isManager, isSeller } = useAuth()

  if (!user) {
    return <Navigate to="/login" replace />
  }

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
          <a className="sidebar__link sidebar__link--active" href="#">Дашборд</a>
          {(isAdmin || isManager) && <a className="sidebar__link" href="#">Приёмка</a>}
          {(isAdmin || isManager) && <a className="sidebar__link" href="#">Заказы</a>}
          {(isAdmin || isManager) && <a className="sidebar__link" href="#">Поставки</a>}
          {isAdmin && <a className="sidebar__link" href="#">Селлеры</a>}
          {isSeller && <a className="sidebar__link" href="#">Мои остатки</a>}
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
        <header className="topbar">
          <div>
            <h1>Дашборд склада</h1>
            <p>
              {isSeller && user.seller_name
                ? `Кабинет селлера: ${user.seller_name}`
                : 'Обзор операций фулфилмента · обновление каждые 15 мин'}
            </p>
          </div>
          {(isAdmin || isManager || isSeller) && (
            <button type="button" className="btn btn--primary">
              Обновить данные WB
            </button>
          )}
        </header>

        <section className="stats-grid">
          <StatCard
            label="Заказов сегодня"
            value="—"
            hint={isSeller ? 'Ваши заказы' : 'Синхронизация с WB'}
            tone="blue"
          />
          {isAdmin && (
            <StatCard label="Селлеров" value="—" hint="Подключено к API" tone="purple" />
          )}
          {(isAdmin || isManager) && (
            <StatCard label="На сборке" value="—" hint="Лист подбора" tone="orange" />
          )}
          <StatCard
            label={isSeller ? 'Мои остатки (SKU)' : 'Остатков (SKU)'}
            value="—"
            hint="По ячейкам склада"
            tone="green"
          />
        </section>

        {(isAdmin || isManager) && <ProcessFlow />}

        <section className="panels">
          <div className="panel">
            <h2 className="section-title">Ваш доступ</h2>
            <div className="roles-grid">
              {isAdmin && (
                <article className="role-card role-card--admin">
                  <h3>Администратор</h3>
                  <p>Селлеры, финансы, цены, отчёты, полный доступ к системе</p>
                </article>
              )}
              {isManager && (
                <article className="role-card role-card--manager">
                  <h3>Менеджер склада</h3>
                  <p>Приёмка, сборка, поставки — без цен и финансовых данных</p>
                </article>
              )}
              {isSeller && (
                <article className="role-card role-card--seller">
                  <h3>Селлер</h3>
                  <p>Только ваши остатки и заказы, без данных других селлеров</p>
                </article>
              )}
            </div>
          </div>

          <div className="panel panel--accent">
            <h2 className="section-title">Статус разработки</h2>
            <ul className="checklist">
              <li className="checklist__item checklist__item--done">Авторизация JWT + роли</li>
              <li className="checklist__item checklist__item--done">Backend + Docker на сервере</li>
              <li className="checklist__item">API складских операций</li>
              <li className="checklist__item">Интеграция Wildberries FBS</li>
              <li className="checklist__item">Печать этикеток Xprinter</li>
            </ul>
          </div>
        </section>
      </div>
    </div>
  )
}
