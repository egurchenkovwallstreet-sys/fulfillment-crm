import type { AssemblyOrder } from '../api/assembly'
import { ApiError } from '../api/client'
import { appendStickerHint } from './stickerLabel'

export type WorkflowStepId = 1 | 2 | 3 | 4

export type ScanPhase = 'barcode' | 'marking'

export const WORKFLOW_STEPS = [
  {
    id: 1 as WorkflowStepId,
    title: 'Лист подбора',
    hint: '«Сформировать лист подбора» → «Скачать PDF» — на вкладках Новые и На сборке (можно повторно после передачи)',
  },
  {
    id: 2 as WorkflowStepId,
    title: 'Скан баркода',
    hint: 'Активное окно скана на вкладке «На сборке»',
  },
  {
    id: 3 as WorkflowStepId,
    title: 'Честный знак',
    hint: 'Скан DataMatrix → привязка к стикеру в WB → сразу печать. Заказ сразу в «Готовые»',
  },
  {
    id: 4 as WorkflowStepId,
    title: 'В доставку',
    hint: 'Кнопка зелёная, когда WB принял все ЧЗ без ошибок. Красная — пока проверяет',
  },
] as const

export function isWbNew(order: AssemblyOrder): boolean {
  const wb = (order.wb_supplier_status || '').trim()
  return wb === '' || wb === 'new'
}

export function orderStickerPrinted(order: AssemblyOrder): boolean {
  return order.status === 'label_printed' || order.status === 'marked'
}

export function orderCanDeliver(order: AssemblyOrder): boolean {
  return Boolean(order.can_send_to_delivery)
}

export function orderChzPending(order: AssemblyOrder): boolean {
  return Boolean(order.requires_marking && order.marking_verify_status === 'pending')
}

export function orderNeedsChzVerify(order: AssemblyOrder): boolean {
  if (order.marking_verify_status === 'error') return false
  if (orderCanDeliver(order)) return false
  if (order.marking_verify_status === 'pending') return true
  if (!order.requires_marking) return false
  return !order.marking_bound
}

export function assemblyDeliveryUnlocked(status: {
  errors_count: number
  ready: AssemblyOrder[]
}): boolean {
  if (status.errors_count > 0) return false
  if (status.ready.length === 0) return false
  return status.ready.some(orderCanDeliver)
}

export function orderBlockReason(order: AssemblyOrder): string | null {
  if ((order.wb_supplier_status || '').trim() !== 'confirm') {
    return 'Сначала передайте заказы на сборку в WB (шаг 1)'
  }
  if (!orderStickerPrinted(order)) {
    if (order.requires_marking && order.status === 'assembled') {
      return 'Отсканируйте Честный знак (DataMatrix) — затем печать стикера'
    }
    return 'Отсканируйте баркод и распечатайте стикер FBS'
  }
  if (order.requires_marking && !order.marking_bound) {
    if (order.marking_verify_status === 'pending') {
      return 'WB проверяет ЧЗ (несколько минут) — в доставку после подтверждения'
    }
    if (order.marking_verify_status === 'error') {
      return appendStickerHint(
        order.marking_verify_error || 'ЧЗ отклонён WB — замените товар',
        order,
      )
    }
    return 'Привяжите Честный знак (DataMatrix)'
  }
  if (!order.can_send_to_delivery) {
    return 'Заказ не готов к доставке'
  }
  return null
}

export function resolveWorkflowStep(
  stage: string,
  scanPhase: ScanPhase,
  hasReadyToDeliver: boolean,
): WorkflowStepId {
  if (stage === 'new') return 1
  if (stage === 'complete') return 4
  if (scanPhase === 'marking') return 3
  if (hasReadyToDeliver) return 4
  if (stage === 'confirm') return 2
  return 1
}

export function buildDeliveryConfirmMessage(order: AssemblyOrder): string {
  const lines = [
    `Передать заказ WB #${order.wb_order_id} в доставку?`,
    '',
    'Проверьте перед подтверждением:',
    '✓ Товар собран',
    '✓ Стикер FBS напечатан и наклеен',
  ]
  if (order.requires_marking) {
    lines.push('✓ Честный знак подтверждён WB')
  }
  lines.push('', 'После подтверждения будет напечатан QR поставки.')
  return lines.join('\n')
}

export type StageKey = 'new' | 'confirm' | 'complete'

export function canSwitchToStage(
  target: StageKey,
  counts: Record<string, number>,
): { ok: true } | { ok: false; reason: string } {
  if (target === 'new') return { ok: true }
  if (target === 'confirm') {
    if ((counts.in_picking ?? 0) < 1) {
      return {
        ok: false,
        reason: 'Сначала передайте заказы на сборку в WB (кнопка «Передать на сборку»).',
      }
    }
    return { ok: true }
  }
  if ((counts.in_delivery ?? 0) < 1) {
    return {
      ok: false,
      reason: 'Нет заказов в поставках, ожидающих приёмки на складе WB.',
    }
  }
  return { ok: true }
}

const SCAN_ERROR_TITLES: Record<string, string> = {
  duplicate_marking: 'ЧЗ уже использован сегодня',
  wb_bind_failed: 'WB отклонил Честный знак',
  invalid_marking_code: 'Неверный код ЧЗ',
  insufficient_stock: 'Недостаточно остатка на складе',
  no_sticker: 'Стикер не загружен',
  wb_not_confirm: 'Заказ не на сборке в WB',
  not_in_pick_list: 'Баркода нет в листе подбора',
  already_printed: 'Стикер уже напечатан',
  invalid_status: 'Заказ в неподходящем статусе',
  marking_not_required: 'ЧЗ не требуется',
  order_not_found: 'Заказ не найден',
}

export function assemblyScanErrorTitle(err: unknown, fallback = 'Ошибка сканирования'): string {
  if (!(err instanceof ApiError) || !err.code) return fallback
  return SCAN_ERROR_TITLES[err.code] ?? fallback
}
