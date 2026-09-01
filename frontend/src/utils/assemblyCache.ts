import type { AssemblySellerDetail, SellerAssemblyCounters } from '../api/assembly'

const SELLERS_PREFIX = 'ff_assembly_sellers:'
const SELLER_PREFIX = 'ff_assembly_seller:'

function sellersKey(marketplace: string): string {
  return `${SELLERS_PREFIX}${marketplace}`
}

function sellerKey(sellerId: number, stage: string): string {
  return `${SELLER_PREFIX}${sellerId}:${stage || 'new'}`
}

export function readAssemblySellersCache(marketplace: string): SellerAssemblyCounters[] | null {
  try {
    const raw = sessionStorage.getItem(sellersKey(marketplace))
    if (!raw) return null
    const parsed = JSON.parse(raw) as SellerAssemblyCounters[]
    return Array.isArray(parsed) ? parsed : null
  } catch {
    return null
  }
}

export function writeAssemblySellersCache(marketplace: string, sellers: SellerAssemblyCounters[]): void {
  try {
    sessionStorage.setItem(sellersKey(marketplace), JSON.stringify(sellers))
  } catch {
    // ignore quota errors
  }
}

export function readAssemblySellerCache(
  sellerId: number,
  stage: string,
): AssemblySellerDetail | null {
  try {
    const raw = sessionStorage.getItem(sellerKey(sellerId, stage))
    if (!raw) return null
    return JSON.parse(raw) as AssemblySellerDetail
  } catch {
    return null
  }
}

export function writeAssemblySellerCache(
  sellerId: number,
  stage: string,
  detail: AssemblySellerDetail,
): void {
  try {
    sessionStorage.setItem(sellerKey(sellerId, stage || 'new'), JSON.stringify(detail))
  } catch {
    // ignore quota errors
  }
}
