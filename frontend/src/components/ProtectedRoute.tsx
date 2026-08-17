import { Navigate, Outlet } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

export function ProtectedRoute() {
  const { user, loading } = useAuth()

  if (loading) {
    return (
      <div className="loading-screen">
        <div className="loading-screen__spinner" />
        <p>Загрузка…</p>
      </div>
    )
  }

  if (!user) {
    return <Navigate to="/login" replace />
  }

  return <Outlet />
}

export function ManagerRoute() {
  const { user, isAdmin, isManager } = useAuth()

  if (!user) {
    return <Navigate to="/login" replace />
  }

  if (!isAdmin && !isManager) {
    return <Navigate to="/" replace />
  }

  return <Outlet />
}
