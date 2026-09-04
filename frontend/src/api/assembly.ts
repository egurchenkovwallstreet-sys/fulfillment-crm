import { apiFetch } from './client'
import type { PickList } from './orders'

export type { PickList }
import type { SellerWarehouse } from './sellers'

export interface SellerAssemblyCounters {
  id: number
  company_name: string
  new: number
  in_picking: number
  in_delivery: number
  assembled: number
  label_printed: number
  marked: number
  in_supply: number
  shipped: number
  cancelled?: number
  total_active: number
  marketplace?: string
  has_ozon_api?: boolean
}

export interface AssemblyOrder {
  id: number
  wb_order_id: number
  posting_number?: string
  barcode: string
  photo_url: string
  tech_size: string
  cell_number: string
  product_name?: string
  quantity?: number
  status: string
  status_display: string
  wb_supplier_status: string
  wb_status: string
  wb_stage_display: string
  has_sticker: boolean
  sticker_part_a: string
  sticker_part_b: string
  marking_bound: boolean
  marking_bound_count?: number
  marking_needed_count?: number
  marking_verify_status?: string
  marking_verify_error?: string
  requires_marking: boolean
  can_send_to_assembly: boolean
  can_send_to_delivery: boolean
  can_print_label?: boolean
  delivery_method_id?: number | null
  carriage_id?: number | null
  warehouse_quantity: number | null
  fulfillment_coverage?: 'our' | 'unknown'
  created_at: string
}

export interface DeliverySupply {
  id: number
  wb_supply_id: string
  wb_warehouse_id: number | null
  orders_count: number
  supply_barcode_printed: boolean
  created_at: string
}

export interface AssemblySellerDetail {
  seller: { id: number; company_name: string }
  assembly_workflow_mode?: 'scan' | 'batch'
  counts: Record<string, number>
  assembly_eligible?: number
  supplies_forming: number
  warehouses: SellerWarehouse[]
  orders: AssemblyOrder[]
  delivery_supplies?: DeliverySupply[]
  active_pick_list?: PickList | null
  pick_list?: PickList | null
  marketplace?: string
  ozon_assembly_ready?: boolean
  message?: string
}

export interface StartAssemblyResult {
  success: boolean
  orders_count: number
  wb_assembly_sent?: number
  wb_assembly_errors?: string[]
  stickers_fetched: number
  sticker_errors: string
  supplies?: number
  pick_list: PickList | null
}

export interface PickListPreviewResult {
  success: boolean
  pick_list: PickList & {
    preview?: boolean
    warehouse_label?: string
    orders_in_list?: number
    orders_skipped?: number
  }
}

export function previewPickList(sellerId: number, stage: 'new' | 'confirm' = 'new') {
  return apiFetch<PickListPreviewResult>(
    `/api/orders/assembly/sellers/${sellerId}/pick-list-preview/`,
    {
      method: 'POST',
      body: JSON.stringify({ stage }),
    },
  )
}

export interface PrintOrder {
  id: number
  wb_order_id: number
  barcode: string
  status: string
  status_display: string
  sticker_file: string
  sticker_part_a: string
  sticker_part_b: string
  has_sticker: boolean
  requires_marking: boolean
  marking_bound: boolean
  marking_verify_status?: string
  marking_verify_error?: string
  cell_number?: string
  can_send_to_delivery: boolean
}

export interface ScanBarcodeResult {
  success: boolean
  action: 'print' | 'await_marking'
  requires_marking: boolean
  message?: string
  order: PrintOrder
}

export interface BindMarkingResult {
  success: boolean
  action: 'await_verification' | 'print'
  message?: string
  order: PrintOrder
}

export interface MarkingVerifyItem {
  order_id: number
  wb_order_id: number
  status: 'pending' | 'verified' | 'error'
  decision: string
  error: string
  marking_bound: boolean
  order?: PrintOrder
}

export interface VerifyMarkingResult {
  success: boolean
  results: MarkingVerifyItem[]
}

export interface ReplaceOrderResult {
  success: boolean
  message: string
  order: AssemblyOrder
}

export interface SendToAssemblyResult {
  success: boolean
  order: AssemblyOrder
  wb_supply_id: string
  stickers_fetched: number
  sticker_error?: string
}

export interface SendAllToAssemblyResult {
  success: boolean
  sent: number
  total: number
  stickers_fetched: number
  errors: Array<{ order_id: number; wb_order_id: number; error: string }>
}

export interface SendToDeliveryResult {
  success: boolean
  order: AssemblyOrder
  wb_supply_id: string
  supply_id?: number
  supply_barcode_file?: string
  supply_barcode?: string
  supply_barcode_error?: string
  stock?: {
    deducted: boolean
    already_deducted: boolean
    quantity: number
    cell_number: string
    barcode: string
  }
}

export function fetchAssemblySellers() {
  return apiFetch<SellerAssemblyCounters[]>('/api/orders/assembly/sellers/')
}

export function fetchAssemblySeller(sellerId: number, stage?: string) {
  const qs = stage ? `?stage=${stage}` : ''
  return apiFetch<AssemblySellerDetail>(`/api/orders/assembly/sellers/${sellerId}/${qs}`)
}

export function reprintOrderSticker(sellerId: number, orderId: number, confirmed = true) {
  return apiFetch<ScanBarcodeResult>(
    `/api/orders/assembly/sellers/${sellerId}/reprint-sticker/`,
    {
      method: 'POST',
      body: JSON.stringify({ order_id: orderId, confirmed }),
    },
  )
}

export function startAssembly(sellerId: number) {
  return apiFetch<StartAssemblyResult>(`/api/orders/assembly/sellers/${sellerId}/start/`, {
    method: 'POST',
    body: '{}',
  })
}

export interface DeletePickListResult {
  success: boolean
  deleted_pick_list_id: number
  orders_unlocked: number
}

export interface DeleteOrderResult {
  success: boolean
  order: AssemblyOrder
  counts: Record<string, number>
  assembly_eligible: number
}

export function deleteAssemblyOrder(sellerId: number, orderId: number) {
  return apiFetch<DeleteOrderResult>(
    `/api/orders/assembly/sellers/${sellerId}/delete-order/`,
    {
      method: 'POST',
      body: JSON.stringify({ order_id: orderId }),
    },
  )
}

export function deletePickList(sellerId: number, pickListId?: number) {
  return apiFetch<DeletePickListResult>(
    `/api/orders/assembly/sellers/${sellerId}/delete-pick-list/`,
    {
      method: 'POST',
      body: JSON.stringify(pickListId ? { pick_list_id: pickListId } : {}),
    },
  )
}

export function scanOrderBarcode(sellerId: number, barcode: string) {
  return apiFetch<ScanBarcodeResult>(`/api/orders/assembly/sellers/${sellerId}/scan-print/`, {
    method: 'POST',
    body: JSON.stringify({ barcode }),
  })
}

export type AssemblyWorkflowMode = 'scan' | 'batch'

export function setAssemblyWorkflowMode(sellerId: number, mode: AssemblyWorkflowMode) {
  return apiFetch<{ success: boolean; assembly_workflow_mode: AssemblyWorkflowMode }>(
    `/api/orders/assembly/sellers/${sellerId}/workflow-mode/`,
    {
      method: 'POST',
      body: JSON.stringify({ mode }),
    },
  )
}

export type BatchRibbonItem =
  | {
      type: 'info'
      cell_number: string
      tech_size: string
      barcode: string
      article: string
      quantity: number
    }
  | {
      type: 'sticker'
      format: 'png' | 'pdf_bulk' | 'posting_number'
      order_id?: number
      wb_order_id?: number
      posting_id?: number
      posting_number?: string
      barcode?: string
      sticker_file?: string
      sticker_part_a?: string
      sticker_part_b?: string
      pdf_base64?: string
      requires_marking?: boolean
    }

export interface BatchRibbonResult {
  success: boolean
  pick_list_id: number
  marketplace: string
  items: BatchRibbonItem[]
  groups_count: number
  stickers_count: number
  labels_from_ozon?: boolean
}

export function fetchBatchRibbon(sellerId: number) {
  return apiFetch<BatchRibbonResult>(`/api/orders/assembly/sellers/${sellerId}/batch-ribbon/`, {
    method: 'POST',
    body: '{}',
  })
}

export interface BatchBindState {
  barcode: string
  sticker_scan: string
  marking_code: string
}

export interface BatchBindResult extends BatchBindState {
  success: boolean
  complete: boolean
  requires_marking?: boolean
  scan_kind?: string
  message?: string
  order_id?: number
  wb_order_id?: number
  posting_id?: number
  posting_number?: string
  order?: PrintOrder
}

export function batchBindScan(
  sellerId: number,
  payload: BatchBindState & { scan?: string },
) {
  return apiFetch<BatchBindResult>(`/api/orders/assembly/sellers/${sellerId}/batch-bind/`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function generateOzonPickList(sellerId: number) {
  return apiFetch<{ success: boolean; pick_list: PickList }>(
    `/api/orders/assembly/sellers/${sellerId}/ozon-pick-list/`,
    {
      method: 'POST',
      body: '{}',
    },
  )
}

export function bindMarking(sellerId: number, orderId: number, markingCode: string) {
  return apiFetch<BindMarkingResult>(`/api/orders/assembly/sellers/${sellerId}/bind-marking/`, {
    method: 'POST',
    body: JSON.stringify({ order_id: orderId, marking_code: markingCode }),
  })
}

export interface AssemblyQueueStatus {
  success: boolean
  in_assembly_count: number
  ready_count: number
  errors_count: number
  in_assembly: AssemblyOrder[]
  ready: AssemblyOrder[]
  errors: AssemblyOrder[]
}

/** @deprecated use AssemblyQueueStatus */
export type MarkingStatusResult = AssemblyQueueStatus

export function fetchAssemblyQueueStatus(sellerId: number) {
  return apiFetch<AssemblyQueueStatus>(`/api/orders/assembly/sellers/${sellerId}/marking-status/`)
}

/** @deprecated use fetchAssemblyQueueStatus */
export function fetchMarkingStatus(sellerId: number) {
  return fetchAssemblyQueueStatus(sellerId)
}

export function verifyMarking(sellerId: number, orderIds?: number[]) {
  return apiFetch<VerifyMarkingResult>(`/api/orders/assembly/sellers/${sellerId}/verify-marking/`, {
    method: 'POST',
    body: JSON.stringify({ order_ids: orderIds ?? [] }),
  })
}

export function replaceOrderItem(sellerId: number, orderId: number) {
  return apiFetch<ReplaceOrderResult>(`/api/orders/assembly/sellers/${sellerId}/replace-order/`, {
    method: 'POST',
    body: JSON.stringify({ order_id: orderId }),
  })
}

export function sendOrderToAssembly(sellerId: number, orderId: number) {
  return apiFetch<SendToAssemblyResult>(
    `/api/orders/assembly/sellers/${sellerId}/send-to-assembly/`,
    {
      method: 'POST',
      body: JSON.stringify({ order_id: orderId }),
    },
  )
}

export function sendAllOrdersToAssembly(sellerId: number) {
  return apiFetch<SendAllToAssemblyResult>(
    `/api/orders/assembly/sellers/${sellerId}/send-all-to-assembly/`,
    {
      method: 'POST',
      body: '{}',
    },
  )
}

export function sendOrderToDelivery(sellerId: number, orderId: number) {
  return apiFetch<SendToDeliveryResult>(
    `/api/orders/assembly/sellers/${sellerId}/send-to-delivery/`,
    {
      method: 'POST',
      body: JSON.stringify({ order_id: orderId }),
    },
  )
}

export function fetchSupplyBarcode(supplyId: number) {
  return apiFetch<{
    success: boolean
    wb_supply_id: string
    supply_barcode_file: string
    supply_barcode?: string
  }>(`/api/orders/supplies/${supplyId}/barcode/`)
}

/** @deprecated use scanOrderBarcode */
export function scanPrintSticker(sellerId: number, barcode: string) {
  return scanOrderBarcode(sellerId, barcode)
}

export function scanOzonBarcode(sellerId: number, barcode: string) {
  return apiFetch<{
    success: boolean
    message: string
    action?: 'scanned' | 'await_marking'
    posting: AssemblyOrder
    counts: Record<string, number>
  }>(`/api/orders/assembly/sellers/${sellerId}/ozon-scan/`, {
    method: 'POST',
    body: JSON.stringify({ barcode }),
  })
}

export function bulkMoveOzonToAssembly(sellerId: number, postingIds: number[]) {
  return apiFetch<{
    success: boolean
    message: string
    moved_count?: number
    skipped?: Array<{ posting_id: number; error: string }>
    counts: Record<string, number>
  }>(`/api/orders/assembly/sellers/${sellerId}/ozon-scan/`, {
    method: 'POST',
    body: JSON.stringify({ posting_ids: postingIds }),
  })
}

export function bindOzonMarking(sellerId: number, postingId: number, markingCode: string) {
  return apiFetch<{
    success: boolean
    message: string
    action?: 'await_marking' | 'bound'
    posting: AssemblyOrder
    counts: Record<string, number>
  }>(`/api/orders/assembly/sellers/${sellerId}/ozon-bind-marking/`, {
    method: 'POST',
    body: JSON.stringify({ posting_id: postingId, marking_code: markingCode }),
  })
}

export function shipOzonPosting(sellerId: number, postingId: number) {
  return apiFetch<{
    success: boolean
    message: string
    posting: AssemblyOrder
    counts: Record<string, number>
    stock?: SendToDeliveryResult['stock']
  }>(`/api/orders/assembly/sellers/${sellerId}/ozon-ship/`, {
    method: 'POST',
    body: JSON.stringify({ posting_id: postingId }),
  })
}

export function bulkShipOzonPostings(sellerId: number, postingIds: number[]) {
  return apiFetch<{
    success: boolean
    message: string
    shipped_count?: number
    errors?: Array<{ posting_id: number; error: string }>
    counts: Record<string, number>
  }>(`/api/orders/assembly/sellers/${sellerId}/ozon-ship/`, {
    method: 'POST',
    body: JSON.stringify({ posting_ids: postingIds }),
  })
}

export function fetchOzonLabel(sellerId: number, postingId: number) {
  return apiFetch<{
    success: boolean
    filename: string
    pdf_base64: string
    posting?: AssemblyOrder
    count?: number
  }>(`/api/orders/assembly/sellers/${sellerId}/ozon-label/`, {
    method: 'POST',
    body: JSON.stringify({ posting_id: postingId }),
  })
}

export function fetchOzonLabelsBulk(sellerId: number, postingIds: number[]) {
  return apiFetch<{
    success: boolean
    filename: string
    pdf_base64: string
    count?: number
  }>(`/api/orders/assembly/sellers/${sellerId}/ozon-label/`, {
    method: 'POST',
    body: JSON.stringify({ posting_ids: postingIds }),
  })
}

export type OzonActResult = {
  success: boolean
  message?: string
  carriage_id?: number
  barcode_file?: string
  pdf_base64?: string
  filename?: string
  warning?: string
  acts?: Array<{
    delivery_method_id: number
    carriage_id: number
    posting_count: number
    barcode_file: string
    pdf_base64: string
    filename: string
    warning: string
  }>
}

export function formOzonAct(sellerId: number, carriageId?: number) {
  return apiFetch<OzonActResult>(`/api/orders/assembly/sellers/${sellerId}/ozon-act/`, {
    method: 'POST',
    body: JSON.stringify(carriageId ? { carriage_id: carriageId } : {}),
  })
}

export function syncOzonAssembly(sellerId: number, stage?: string) {
  return apiFetch<AssemblySellerDetail>(`/api/orders/assembly/sellers/${sellerId}/ozon-sync/`, {
    method: 'POST',
    body: JSON.stringify({ stage: stage || 'new' }),
  })
}
