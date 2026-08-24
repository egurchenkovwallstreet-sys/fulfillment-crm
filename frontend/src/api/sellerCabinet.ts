import { apiFetch } from './client'

export type PeriodMetric = {
  current: number
  previous: number
  change_pct: number | null
  direction: 'up' | 'down' | 'flat' | 'new'
}

export type SellerCabinetSummary = {
  orders_day: PeriodMetric
  orders_week: PeriodMetric
  orders_month: PeriodMetric
  sku_count: number
  total_stock: number
}

export type SellerWbStageCounts = {
  new: number
  in_picking: number
  in_delivery: number
}

export type SellerWeeklyShipmentDay = {
  date: string
  weekday: string
  orders: number
  amount: string
}

export type SellerWeeklyShipmentWeek = {
  week_start: string
  week_end: string
  total: number
  total_amount: string
  supplies_count: number
  is_current: boolean
  days: SellerWeeklyShipmentDay[]
}

export type SellerWeeklyShipments = {
  today: string
  weeks: SellerWeeklyShipmentWeek[]
}

export type StockLevel = 'urgent' | 'restock' | 'sufficient' | 'excess'

export type SellerBarcodeItem = {
  barcode: string
  name: string
  tech_size: string
  photo_url: string
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
  wb_stages: SellerWbStageCounts
  weekly_shipments: SellerWeeklyShipments
  items: SellerBarcodeItem[]
  meta?: {
    enabled_warehouses: { wb_warehouse_id: number; name: string }[]
    source: string
    timezone?: string
  }
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
