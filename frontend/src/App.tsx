import './App.css'

function App() {
  return (
    <div className="app">
      <header className="app-header">
        <h1>Fulfillment CRM / WMS</h1>
        <p>Система управления фулфилментом для Wildberries FBS</p>
      </header>

      <main className="app-main">
        <section className="status-card">
          <h2>Статус проекта</h2>
          <p>Инициализация завершена. Backend и frontend готовы к разработке.</p>
          <ul>
            <li>Backend: Django + PostgreSQL + Celery</li>
            <li>Frontend: React + Vite + TypeScript</li>
            <li>Документация: TZ.md, PROGRESS.md</li>
          </ul>
        </section>

        <section className="roles-card">
          <h2>Роли</h2>
          <div className="roles-grid">
            <div className="role">
              <strong>Администратор</strong>
              <span>Полный доступ, финансы</span>
            </div>
            <div className="role">
              <strong>Менеджер</strong>
              <span>Склад и заказы, без финансов</span>
            </div>
            <div className="role">
              <strong>Селлер</strong>
              <span>Только свои данные</span>
            </div>
          </div>
        </section>
      </main>
    </div>
  )
}

export default App
