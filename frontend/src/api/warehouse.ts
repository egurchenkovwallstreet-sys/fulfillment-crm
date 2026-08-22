import { apiFetch } from './client'

export type Seller = {
  id: number
  company_name: string
}

export type Cell = {
  id: number
  number: string
  is_occupied: boolean
}

export type Product = {
  id: number
  barcode: string
  name: string
  quantity: number
  cell: number
  cell_number: string
  seller: number
  seller_name: string
  requires_marking: boolean
}

export type StockMode = 'intake' | 'sync_from_wb'

export type IntakeLookup = {
  exists: boolean
  barcode?: string
  product?: Product
  wb_stock?: number | null
  warehouse_name?: string
  marking?: {
    requires_marking: boolean
    wb_found: boolean
    title?: string
    warning?: string
  }
}

export type IntakeHistoryItem = {
  id: number
  barcode: string
  cell_number: string
  seller_name: string
  operation_type: string
  quantity: number
  comment: string
  created_at: string
}

export type IntakePayload = {
  seller_id: number
  wb_warehouse_id: number
  barcode: string
  quantity: number
  stock_mode: StockMode
  verified_stock_match?: boolean
  cell_mode: 'auto' | 'manual'
  cell_id?: number | null
  name?: string
}

export type CellLabelData = {
  product_id?: number
  seller_name: string
  cell_number: string
  barcode: string
}

export type IntakeResponse = {
  success: boolean
  message: string
  product: Product
  print_cell_label?: boolean
  cell_label?: CellLabelData | null
  stock_mode?: StockMode
  wb_sync?: {
    wb_warehouse_id?: number
    warehouse_name?: string
    previous_wb_amount?: number
    new_wb_amount?: number
    added?: number
    wb_amount?: number
    mode?: string
  } | null
}

export type MoveCellResponse = {
  success: boolean
  message: string
  product: Product
  print_cell_label: boolean
  cell_label: CellLabelData
}

export type RefreshFromWbResponse = {
  success: boolean
  message: string
  total: number
  updated: number
  not_found: number
  products: Product[]
  detail?: string
}

export function fetchSellers() {
  return apiFetch<Seller[]>('/api/warehouse/sellers/')
}

export function fetchFreeCells() {
  return apiFetch<Cell[]>('/api/warehouse/cells/?free=1')
}

export function fetchAllCells() {
  return apiFetch<Cell[]>('/api/warehouse/cells/')
}

export function fetchSellerProducts(sellerId: number) {
  return apiFetch<Product[]>(`/api/warehouse/sellers/${sellerId}/products/`)
}

export function refreshSellerProductsFromWb(sellerId: number) {
  return apiFetch<RefreshFromWbResponse>(
    `/api/warehouse/sellers/${sellerId}/products/refresh-from-wb/`,
    { method: 'POST' },
  )
}

export function fetchProductCellLabel(productId: number) {
  return apiFetch<CellLabelData>(`/api/warehouse/products/${productId}/cell-label/`)
}

export function moveProductToCell(productId: number, cellId: number) {
  return apiFetch<MoveCellResponse>(`/api/warehouse/products/${productId}/move-cell/`, {
    method: 'POST',
    body: JSON.stringify({ cell_id: cellId }),
  })
}

export function lookupBarcode(sellerId: number, barcode: string, warehouseId?: number) {
  const params = new URLSearchParams({
    seller_id: String(sellerId),
    barcode,
  })
  if (warehouseId) {
    params.set('wb_warehouse_id', String(warehouseId))
  }
  return apiFetch<IntakeLookup>(`/api/warehouse/intake/lookup/?${params}`)
}

export function submitIntake(payload: IntakePayload) {
  return apiFetch<IntakeResponse>(
    '/api/warehouse/intake/',
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
  )
}

export function fetchIntakeHistory() {
  return apiFetch<IntakeHistoryItem[]>('/api/warehouse/intake/history/')
}
