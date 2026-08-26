import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { useAuth } from './AuthContext'
import {
  getStoredMarketplace,
  setStoredMarketplace,
  type Marketplace,
} from '../utils/marketplace'

type MarketplaceContextValue = {
  marketplace: Marketplace
  setMarketplace: (next: Marketplace) => void
  canUseWb: boolean
  canUseOzon: boolean
  showSwitcher: boolean
}

const MarketplaceContext = createContext<MarketplaceContextValue | null>(null)

function clampMarketplace(
  next: Marketplace,
  canUseWb: boolean,
  canUseOzon: boolean,
): Marketplace {
  if (next === 'ozon' && canUseOzon) return 'ozon'
  if (next === 'wb' && canUseWb) return 'wb'
  if (canUseOzon && !canUseWb) return 'ozon'
  return 'wb'
}

export function MarketplaceProvider({ children }: { children: ReactNode }) {
  const { user, isSeller } = useAuth()
  const canUseWb = isSeller ? Boolean(user?.wb_enabled) : true
  const canUseOzon = isSeller ? Boolean(user?.ozon_enabled) : true
  const showSwitcher = canUseWb && canUseOzon

  const [marketplace, setMarketplaceState] = useState<Marketplace>(() =>
    clampMarketplace(getStoredMarketplace(), true, true),
  )

  useEffect(() => {
    const next = clampMarketplace(getStoredMarketplace(), canUseWb, canUseOzon)
    setMarketplaceState(next)
    setStoredMarketplace(next)
  }, [canUseWb, canUseOzon, user?.id])

  const setMarketplace = useCallback(
    (next: Marketplace) => {
      const clamped = clampMarketplace(next, canUseWb, canUseOzon)
      setMarketplaceState(clamped)
      setStoredMarketplace(clamped)
    },
    [canUseWb, canUseOzon],
  )

  const value = useMemo(
    () => ({ marketplace, setMarketplace, canUseWb, canUseOzon, showSwitcher }),
    [marketplace, setMarketplace, canUseWb, canUseOzon, showSwitcher],
  )

  return <MarketplaceContext.Provider value={value}>{children}</MarketplaceContext.Provider>
}

export function useMarketplace() {
  const ctx = useContext(MarketplaceContext)
  if (!ctx) throw new Error('useMarketplace must be used within MarketplaceProvider')
  return ctx
}
