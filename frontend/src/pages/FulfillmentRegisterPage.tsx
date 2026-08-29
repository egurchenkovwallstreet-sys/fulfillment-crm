import { useState, type FormEvent } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { registerFulfillment } from '../api/fulfillmentRegister'
import { saveTokens } from '../api/tokens'
import { useAuth } from '../context/AuthContext'
import { hintWrapProps, uiHint } from '../utils/uiHint'
import '../pages/LoginPage.css'

export function FulfillmentRegisterPage() {
  const { user, setUserFromLogin } = useAuth()
  const navigate = useNavigate()
  const [fulfillmentName, setFulfillmentName] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [email, setEmail] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  if (user) {
    return <Navigate to={user.role === 'seller' ? '/cabinet' : '/owner'} replace />
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      const result = await registerFulfillment({
        fulfillment_name: fulfillmentName.trim(),
        username: username.trim(),
        password,
        email: email.trim() || undefined,
      })
      saveTokens(result.access, result.refresh)
      setUserFromLogin(result.user)
      navigate('/owner')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка регистрации')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <header className="login-card__header">
          <span className="login-card__logo">FF</span>
          <div>
            <h1>Новый фулфилмент</h1>
            <p>Создайте аккаунт оператора и войдите в кабинет владельца</p>
          </div>
        </header>

        <form className="login-form" onSubmit={handleSubmit}>
          <label>
            Название фулфилмента
            <input
              type="text"
              value={fulfillmentName}
              onChange={(e) => setFulfillmentName(e.target.value)}
              placeholder="ИП Иванов FF"
              required
            />
          </label>
          <label>
            Логин владельца
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              required
            />
          </label>
          <label>
            Пароль
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
              minLength={8}
              required
            />
          </label>
          <label>
            Email (необязательно)
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
          </label>
          {error && <p className="login-form__error">{error}</p>}
          <span {...hintWrapProps('Создать аккаунт фулфилмента и войти в кабинет владельца.')}>
            <button type="submit" className="btn btn--primary btn--full" disabled={loading}>
              {loading ? 'Создание…' : 'Создать фулфилмент'}
            </button>
          </span>
        </form>

        <p className="login-card__footer">
          Уже есть аккаунт? <Link to="/login" {...uiHint('Перейти на страницу входа в CRM.')}>Войти</Link>
        </p>
      </div>
    </div>
  )
}
