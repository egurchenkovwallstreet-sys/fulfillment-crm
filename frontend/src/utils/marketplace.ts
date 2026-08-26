export type Marketplace = 'wb' | 'ozon'

export const MARKETPLACE_STORAGE_KEY = 'crm-marketplace'

export function getStoredMarketplace(): Marketplace {
  try {
    return localStorage.getItem(MARKETPLACE_STORAGE_KEY) === 'ozon' ? 'ozon' : 'wb'
  } catch {
    return 'wb'
  }
}

export function setStoredMarketplace(marketplace: Marketplace) {
  try {
    localStorage.setItem(MARKETPLACE_STORAGE_KEY, marketplace)
  } catch {
    // ignore
  }
}

export const MARKETPLACE_LABEL: Record<Marketplace, string> = {
  wb: 'WB',
  ozon: 'Ozon',
}

export const MARKETPLACE_BADGE: Record<Marketplace, string> = {
  wb: 'ВБ',
  ozon: 'OZON',
}
