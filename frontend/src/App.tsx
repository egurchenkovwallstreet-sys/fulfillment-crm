import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AppLayout } from './components/AppLayout'
import { AdminRoute, ManagerRoute, ProtectedRoute, SellerRoute } from './components/ProtectedRoute'
import { AuthProvider, useAuth } from './context/AuthContext'
import { AssemblySellerPage } from './pages/AssemblySellerPage'
import { AssemblySellersPage } from './pages/AssemblySellersPage'
import { DashboardPage } from './pages/DashboardPage'
import { IntakePage } from './pages/IntakePage'
import { CellInventoryPage } from './pages/CellInventoryPage'
import { LoginPage } from './pages/LoginPage'
import { PrintAgentPage } from './pages/PrintAgentPage'
import { SellerBarcodeDetailPage } from './pages/SellerBarcodeDetailPage'
import { SellerCabinetPage } from './pages/SellerCabinetPage'
import { SellerRegisterPage } from './pages/SellerRegisterPage'
import { SellersManagePage } from './pages/SellersManagePage'

function HomeRedirect() {
  const { isSeller } = useAuth()
  if (isSeller) return <Navigate to="/cabinet" replace />
  return <DashboardPage />
}

function AppRoutes() {
  const { user, loading, isSeller } = useAuth()

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
      <Route path="/login" element={user ? <Navigate to={isSeller ? '/cabinet' : '/'} replace /> : <LoginPage />} />
      <Route path="/register/:token" element={<SellerRegisterPage />} />
      <Route element={<ProtectedRoute />}>
        <Route element={<AppLayout />}>
          <Route path="/" element={<HomeRedirect />} />
          <Route element={<SellerRoute />}>
            <Route path="/cabinet" element={<SellerCabinetPage />} />
            <Route path="/cabinet/:barcode" element={<SellerBarcodeDetailPage />} />
          </Route>
          <Route element={<ManagerRoute />}>
            <Route path="/intake" element={<IntakePage />} />
            <Route path="/cells" element={<CellInventoryPage />} />
            <Route path="/assembly" element={<AssemblySellersPage />} />
            <Route path="/assembly/:sellerId" element={<AssemblySellerPage />} />
            <Route path="/print-agent" element={<PrintAgentPage />} />
            <Route path="/orders" element={<AssemblySellersPage />} />
          </Route>
          <Route element={<AdminRoute />}>
            <Route path="/sellers" element={<SellersManagePage />} />
          </Route>
        </Route>
      </Route>
      <Route path="*" element={<Navigate to={user ? (isSeller ? '/cabinet' : '/') : '/login'} replace />} />
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
