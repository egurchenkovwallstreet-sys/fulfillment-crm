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
  photo_url?: string
  tech_size?: string
  wb_size?: string
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
  wb_warehouse_id?: number
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
  marketplace?: string
  marketplace_label?: string
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

export function fetchFreeCells(sellerId: number) {
  return apiFetch<Cell[]>(`/api/warehouse/cells/?seller_id=${sellerId}&free=1`)
}

export function fetchAllCells(sellerId: number) {
  return apiFetch<Cell[]>(`/api/warehouse/cells/?seller_id=${sellerId}`)
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

export type InventoryLookup = {
  exists: boolean
  barcode?: string
  product?: Product
  marking?: {
    requires_marking: boolean
    wb_found: boolean
    title?: string
    warning?: string
  }
}

export type InventoryWarehouseLine = {
  warehouse_id: number
  warehouse_name: string
  wb_warehouse_id: number
  sent_amount: number
  wb_actual: number
  difference: number
}

export type InventoryPayload = {
  seller_id: number
  barcode: string
  quantity: number
  warehouse_ids: number[]
  cell_mode: 'auto' | 'manual'
  cell_id?: number | null
  name?: string
}

export type InventoryResponse = {
  success: boolean
  verified: boolean
  fulfillment_quantity: number
  wb_total_sent: number
  wb_total_actual: number
  wb_total_difference: number
  warehouses: InventoryWarehouseLine[]
  product: Product
  print_cell_label?: boolean
  cell_label?: CellLabelData | null
}

export function lookupInventoryBarcode(sellerId: number, barcode: string) {
  const params = new URLSearchParams({
    seller_id: String(sellerId),
    barcode,
  })
  return apiFetch<InventoryLookup>(`/api/warehouse/inventory/lookup/?${params}`)
}

export function submitInventory(payload: InventoryPayload) {
  return apiFetch<InventoryResponse>('/api/warehouse/inventory/', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}
