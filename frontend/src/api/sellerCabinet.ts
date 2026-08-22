import { apiFetch } from './client'

export type SellerCabinetSummary = {
  orders_day: number
  orders_week: number
  orders_month: number
  sku_count: number
  total_stock: number
}

export type StockLevel = 'critical' | 'sufficient' | 'excess'

export type SellerBarcodeItem = {
  barcode: string
  name: string
  stock_quantity: number
  orders_day: number
  orders_week: number
  orders_month: number
  avg_daily_sales: number
  days_remaining: number | null
  stock_level: StockLevel
}

export type SellerCabinetResponse = {
  seller: { id: number; company_name: string }
  summary: SellerCabinetSummary
  items: SellerBarcodeItem[]
}

export type SellerBarcodeDetail = SellerBarcodeItem & {
  daily_orders: { date: string; orders: number }[]
  sales_lookback_days: number
}

export async function fetchSellerCabinet(): Promise<SellerCabinetResponse> {
  return apiFetch<SellerCabinetResponse>('/api/sellers/cabinet/')
}

export async function fetchSellerBarcodeDetail(barcode: string): Promise<SellerBarcodeDetail> {
  return apiFetch<SellerBarcodeDetail>(`/api/sellers/cabinet/barcode/${encodeURIComponent(barcode)}/`)
}
