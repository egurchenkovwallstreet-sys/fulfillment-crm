import { useEffect, useState, type FormEvent } from 'react'
import { Link, Navigate, useParams } from 'react-router-dom'
import { fetchInvitePreview, registerSeller } from '../api/sellerAdmin'
import { saveTokens } from '../api/tokens'
import { useAuth } from '../context/AuthContext'
import { hintWrapProps, uiHint } from '../utils/uiHint'
import './LoginPage.css'

export function SellerRegisterPage() {
  const { token } = useParams<{ token: string }>()
  const { user, isSeller, logout, setUserFromLogin } = useAuth()
  const [companyName, setCompanyName] = useState('')
  const [hasAccount, setHasAccount] = useState(false)
  const [loading, setLoading] = useState(true)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [email, setEmail] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [notFound, setNotFound] = useState(false)

  useEffect(() => {
    if (!token) {
      setNotFound(true)
      setLoading(false)
      return
    }
    fetchInvitePreview(token)
      .then((data) => {
        setCompanyName(data.company_name)
        setHasAccount(data.has_account)
      })
      .catch(() => setNotFound(true))
      .finally(() => setLoading(false))
  }, [token])

  if (user && isSeller) {
    return <Navigate to="/cabinet" replace />
  }

  if (user && !isSeller) {
    return (
      <div className="login-page">
        <div className="login-card">
          <h1>Регистрация селлера</h1>
          <p>
            Вы вошли как <strong>{user.username}</strong> ({user.role_display ?? user.role}).
            Чтобы зарегистрировать селлера по этой ссылке, выйдите из текущего аккаунта
            или откройте ссылку в режиме инкогнито / другом браузере.
          </p>
          <button type="button" className="btn btn--primary btn--full" onClick={logout} {...uiHint('Выйти из текущего аккаунта, чтобы зарегистрировать селлера по ссылке.')}>
            Выйти и продолжить
          </button>
          <Link to="/" className="btn btn--ghost btn--full" style={{ marginTop: '0.5rem' }} {...uiHint('Вернуться на главную страницу CRM.')}>
            Вернуться в CRM
          </Link>
        </div>
      </div>
    )
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!token) return
    setError('')
    setSubmitting(true)
    try {
      const data = await registerSeller({
        token,
        username: username.trim(),
        password,
        email: email.trim() || undefined,
      })
      saveTokens(data.access, data.refresh)
      setUserFromLogin(data.user)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка регистрации')
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) {
    return (
      <div className="login-page">
        <div className="login-card">
          <p>Загрузка приглашения…</p>
        </div>
      </div>
    )
  }

  if (notFound) {
    return (
      <div className="login-page">
        <div className="login-card">
          <h1>Ссылка недействительна</h1>
          <p>Приглашение не найдено или отключено. Обратитесь к администратору фулфилмента.</p>
          <Link to="/login" className="btn btn--primary btn--full" {...uiHint('Перейти на страницу входа в CRM.')}>
            На страницу входа
          </Link>
        </div>
      </div>
    )
  }

  if (hasAccount) {
    return (
      <div className="login-page">
        <div className="login-card">
          <h1>Аккаунт уже создан</h1>
          <p>
            Для компании <strong>{companyName}</strong> уже зарегистрирован пользователь. Войдите в CRM.
          </p>
          <Link to="/login" className="btn btn--primary btn--full" {...uiHint('Войти в CRM под уже созданным аккаунтом селлера.')}>
            Войти
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-card__header">
          <span className="login-card__logo">FF</span>
          <div>
            <h1>Регистрация селлера</h1>
            <p>{companyName}</p>
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
              minLength={3}
            />
          </label>

          <label>
            Email <span className="form-optional">(необязательно)</span>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
            />
          </label>

          <label>
            Пароль
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
              required
              minLength={8}
            />
          </label>

          {error && <p className="login-form__error">{error}</p>}

          <span {...hintWrapProps('Создать аккаунт селлера и войти в личный кабинет.')}>
            <button type="submit" className="btn btn--primary btn--full" disabled={submitting}>
              {submitting ? 'Создание…' : 'Создать аккаунт'}
            </button>
          </span>
        </form>
      </div>
    </div>
  )
}
