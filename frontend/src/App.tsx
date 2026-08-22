import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AppLayout } from './components/AppLayout'
import { ManagerRoute, ProtectedRoute } from './components/ProtectedRoute'
import { AuthProvider, useAuth } from './context/AuthContext'
import { AssemblySellerPage } from './pages/AssemblySellerPage'
import { AssemblySellersPage } from './pages/AssemblySellersPage'
import { DashboardPage } from './pages/DashboardPage'
import { IntakePage } from './pages/IntakePage'
import { CellInventoryPage } from './pages/CellInventoryPage'
import { LoginPage } from './pages/LoginPage'
import { PrintAgentPage } from './pages/PrintAgentPage'

function AppRoutes() {
  const { user, loading } = useAuth()

  if (loading) {
    return (
      <div className="loading-screen">
        <div className="loading-screen__spinner" />
        <p>Загрузка…</p>
      </div>
    )
  }

  return (
    <Routes>
      <Route path="/login" element={user ? <Navigate to="/" replace /> : <LoginPage />} />
      <Route element={<ProtectedRoute />}>
        <Route element={<AppLayout />}>
          <Route path="/" element={<DashboardPage />} />
          <Route element={<ManagerRoute />}>
            <Route path="/intake" element={<IntakePage />} />
            <Route path="/cells" element={<CellInventoryPage />} />
            <Route path="/assembly" element={<AssemblySellersPage />} />
            <Route path="/assembly/:sellerId" element={<AssemblySellerPage />} />
            <Route path="/print-agent" element={<PrintAgentPage />} />
            <Route path="/orders" element={<AssemblySellersPage />} />
          </Route>
        </Route>
      </Route>
      <Route path="*" element={<Navigate to={user ? '/' : '/login'} replace />} />
    </Routes>
  )
}

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </BrowserRouter>
  )
}

export default App
