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
    return <Navigate to={user.role === 'seller' ? '/cabinet' : '/'} replace />
  }

  return <Outlet />
}

export function AdminRoute() {
  const { user, isAdmin } = useAuth()

  if (!user) {
    return <Navigate to="/login" replace />
  }

  if (!isAdmin) {
    return <Navigate to={user.role === 'seller' ? '/cabinet' : '/'} replace />
  }

  return <Outlet />
}

export function SellerRoute() {
  const { user, isSeller } = useAuth()

  if (!user) {
    return <Navigate to="/login" replace />
  }

  if (!isSeller) {
    return <Navigate to="/" replace />
  }

  return <Outlet />
}
