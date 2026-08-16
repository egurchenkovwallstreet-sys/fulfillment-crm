import { ProcessFlow } from './components/ProcessFlow'
import { StatCard } from './components/StatCard'
import './App.css'

const roles = [
  {
    name: 'Администратор',
    access: 'Селлеры, финансы, цены, отчёты',
    color: 'role-card--admin',
  },
  {
    name: 'Менеджер склада',
    access: 'Приёмка, сборка, поставки — без цен',
    color: 'role-card--manager',
  },
  {
    name: 'Селлер',
    access: 'Только свои остатки и заказы',
    color: 'role-card--seller',
  },
]

function App() {
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
          <a className="sidebar__link" href="#">Приёмка</a>
          <a className="sidebar__link" href="#">Заказы</a>
          <a className="sidebar__link" href="#">Поставки</a>
          <a className="sidebar__link" href="#">Селлеры</a>
        </nav>
        <div className="sidebar__footer">
          <span className="status-dot" /> Система в разработке
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <div>
            <h1>Дашборд склада</h1>
            <p>Обзор операций фулфилмента · обновление каждые 15 мин</p>
          </div>
          <button type="button" className="btn btn--primary">
            Обновить данные WB
          </button>
        </header>

        <section className="stats-grid">
          <StatCard label="Заказов сегодня" value="—" hint="Синхронизация с WB" tone="blue" />
          <StatCard label="Селлеров" value="—" hint="Подключено к API" tone="purple" />
          <StatCard label="На сборке" value="—" hint="Лист подбора" tone="orange" />
          <StatCard label="Остатков (SKU)" value="—" hint="По всем ячейкам" tone="green" />
        </section>

        <ProcessFlow />

        <section className="panels">
          <div className="panel">
            <h2 className="section-title">Роли в системе</h2>
            <div className="roles-grid">
              {roles.map((role) => (
                <article key={role.name} className={`role-card ${role.color}`}>
                  <h3>{role.name}</h3>
                  <p>{role.access}</p>
                </article>
              ))}
            </div>
          </div>

          <div className="panel panel--accent">
            <h2 className="section-title">Статус разработки</h2>
            <ul className="checklist">
              <li className="checklist__item checklist__item--done">ТЗ и архитектура</li>
              <li className="checklist__item checklist__item--done">Backend + Docker на сервере</li>
              <li className="checklist__item checklist__item--done">Модели БД (селлеры, заказы, ячейки)</li>
              <li className="checklist__item">API и авторизация по ролям</li>
              <li className="checklist__item">Интеграция Wildberries FBS</li>
              <li className="checklist__item">Печать этикеток Xprinter</li>
            </ul>
          </div>
        </section>
      </div>
    </div>
  )
}

export default App
