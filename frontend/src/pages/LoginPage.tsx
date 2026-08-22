import { useState, type FormEvent } from 'react'
import { Navigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import './LoginPage.css'

export function LoginPage() {
  const { user, login, isSeller } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  if (user) {
    return <Navigate to={isSeller ? '/cabinet' : '/'} replace />
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      await login(username.trim(), password)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка входа')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-card__header">
          <span className="login-card__logo">FF</span>
          <div>
            <h1>Fulfillment CRM</h1>
            <p>Вход в систему управления складом</p>
          </div>
        </div>

        <form className="login-form" onSubmit={handleSubmit}>
          <label>
            Логин
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              required
              placeholder="admin"
            />
          </label>

          <label>
            Пароль
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
              placeholder="••••••••"
            />
          </label>

          {error && <p className="login-form__error">{error}</p>}

          <button type="submit" className="btn btn--primary btn--full" disabled={submitting}>
            {submitting ? 'Вход…' : 'Войти'}
          </button>
        </form>

        <div className="login-roles">
          <p>Роли в системе:</p>
          <ul>
            <li><strong>Администратор</strong> — полный доступ</li>
            <li><strong>Менеджер</strong> — склад, без финансов</li>
            <li><strong>Селлер</strong> — только свои данные</li>
          </ul>
        </div>
      </div>
    </div>
  )
}
