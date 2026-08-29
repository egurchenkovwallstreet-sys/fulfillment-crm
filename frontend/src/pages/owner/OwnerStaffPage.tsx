import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { createStaffUser, fetchStaffUsers, updateStaffUser, type StaffUser } from '../../api/staffAdmin'
import { uiHint } from '../../utils/uiHint'
import './OwnerLayout.css'

function formatDate(value: string | null): string {
  if (!value) return '—'
  return new Date(value).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function OwnerStaffPage() {
  const [staff, setStaff] = useState<StaffUser[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [creating, setCreating] = useState(false)
  const [resetUserId, setResetUserId] = useState<number | null>(null)
  const [newPassword, setNewPassword] = useState('')
  const [savingPassword, setSavingPassword] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setStaff(await fetchStaffUsers())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка загрузки')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  async function handleCreate(e: FormEvent) {
    e.preventDefault()
    if (!username.trim() || !password) return
    setCreating(true)
    setMessage('')
    setError('')
    try {
      const createdName = username.trim()
      await createStaffUser({ username: createdName, password })
      setUsername('')
      setPassword('')
      setMessage(`Менеджер «${createdName}» создан`)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка создания')
    } finally {
      setCreating(false)
    }
  }

  async function toggleActive(user: StaffUser) {
    setError('')
    setMessage('')
    try {
      await updateStaffUser(user.id, { is_active: !user.is_active })
      setMessage(user.is_active ? `«${user.username}» отключён` : `«${user.username}» включён`)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка сохранения')
    }
  }

  async function handleResetPassword(e: FormEvent) {
    e.preventDefault()
    if (resetUserId === null || !newPassword) return
    setSavingPassword(true)
    setError('')
    setMessage('')
    try {
      await updateStaffUser(resetUserId, { password: newPassword })
      setMessage('Новый пароль сохранён')
      setResetUserId(null)
      setNewPassword('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка сохранения пароля')
    } finally {
      setSavingPassword(false)
    }
  }

  return (
    <>
      <header className="topbar">
        <div>
          <h1>Сотрудники</h1>
          <p>Менеджеры склада — доступ к операционным разделам без финансов и настроек</p>
        </div>
        <button type="button" className="btn btn--ghost" onClick={load} disabled={loading} {...uiHint('Обновить список менеджеров склада.')}>
          Обновить
        </button>
      </header>

      {error && <div className="dashboard-sync-msg dashboard-sync-msg--error">{error}</div>}
      {message && <div className="dashboard-sync-msg dashboard-sync-msg--ok">{message}</div>}

      <section className="panel">
        <h2 className="section-title">Новый менеджер</h2>
        <form className="owner-pricing-form" onSubmit={handleCreate}>
          <label>
            Логин
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="ivanov"
              required
            />
          </label>
          <label>
            Пароль
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="мин. 8 символов"
              minLength={8}
              required
            />
          </label>
          <button type="submit" className="btn btn--primary" disabled={creating} {...uiHint('Создать учётную запись менеджера склада с указанным логином и паролем.')}>
            {creating ? 'Создание…' : 'Создать'}
          </button>
        </form>
      </section>

      <section className="panel">
        <h2 className="section-title">Список менеджеров</h2>
        {loading && staff.length === 0 && <p>Загрузка…</p>}
        {!loading && staff.length === 0 && <p>Менеджеров пока нет.</p>}
        {staff.length > 0 && (
          <div className="sellers-table-scroll">
            <table className="owner-staff-table">
              <thead>
                <tr>
                  <th>Логин</th>
                  <th>Статус</th>
                  <th>Последний вход</th>
                  <th>Действия</th>
                </tr>
              </thead>
              <tbody>
                {staff.map((user) => (
                  <tr key={user.id}>
                    <td>
                      <strong>{user.username}</strong>
                      {!user.is_active && <span className="owner-tag--inactive">отключён</span>}
                    </td>
                    <td>
                      {user.is_active ? (
                        <span className="owner-tag--ok">активен</span>
                      ) : (
                        <span className="owner-tag--inactive">неактивен</span>
                      )}
                    </td>
                    <td>{formatDate(user.last_login)}</td>
                    <td>
                      <button type="button" className="btn btn--ghost btn--sm" onClick={() => toggleActive(user)} {...uiHint(user.is_active ? 'Запретить вход менеджеру в CRM.' : 'Разрешить менеджеру снова входить в CRM.')}>
                        {user.is_active ? 'Отключить' : 'Включить'}
                      </button>
                      <button
                        type="button"
                        className="btn btn--ghost btn--sm"
                        onClick={() => {
                          setResetUserId(user.id)
                          setNewPassword('')
                        }}
                        {...uiHint('Задать новый пароль для этого менеджера.')}
                      >
                        Сменить пароль
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {resetUserId !== null && (
        <section className="panel">
          <h2 className="section-title">Новый пароль</h2>
          <form className="owner-pricing-form" onSubmit={handleResetPassword}>
            <label>
              Пароль
              <input
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                minLength={8}
                required
              />
            </label>
            <button type="submit" className="btn btn--primary" disabled={savingPassword} {...uiHint('Сохранить новый пароль для выбранного менеджера.')}>
              {savingPassword ? 'Сохранение…' : 'Сохранить'}
            </button>
            <button type="button" className="btn btn--ghost" onClick={() => setResetUserId(null)} {...uiHint('Отменить смену пароля и закрыть форму.')}>
              Отмена
            </button>
          </form>
        </section>
      )}
    </>
  )
}
