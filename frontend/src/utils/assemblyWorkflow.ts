import type { AssemblyOrder } from '../api/assembly'
import { appendStickerHint } from './stickerLabel'

export type WorkflowStepId = 1 | 2 | 3 | 4

export type ScanPhase = 'barcode' | 'marking'

export const WORKFLOW_STEPS = [
  {
    id: 1 as WorkflowStepId,
    title: 'Лист подбора',
    hint: 'Выберите склад → «Сформировать лист подбора» → PDF A4',
  },
  {
    id: 2 as WorkflowStepId,
    title: 'Скан баркода',
    hint: 'Сверка с листом подбора; для ЧЗ — затем шаг 3',
  },
  {
    id: 3 as WorkflowStepId,
    title: 'Честный знак',
    hint: 'Скан DataMatrix → привязка в WB → сразу печать стикера',
  },
  {
    id: 4 as WorkflowStepId,
    title: 'В доставку',
    hint: 'Подтверждение и печать QR поставки 58×40',
  },
] as const

export function isWbNew(order: AssemblyOrder): boolean {
  const wb = (order.wb_supplier_status || '').trim()
  return wb === '' || wb === 'new'
}

export function orderStickerPrinted(order: AssemblyOrder): boolean {
  if (order.requires_marking) {
    return order.status === 'label_printed' || order.status === 'marked'
  }
  return order.status === 'label_printed' || order.has_sticker
}

export function orderCanDeliver(order: AssemblyOrder): boolean {
  if (!order.can_send_to_delivery) return false
  if (order.warehouse_quantity != null && order.warehouse_quantity < 1) return false
  return true
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
  if (order.warehouse_quantity == null) {
    return 'Товар не принят на склад — выполните приёмку'
  }
  if (order.warehouse_quantity < 1) {
    return `Нет остатка на складе (яч. ${order.cell_number || '—'})`
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
    '✓ Товар собран по листу подбора',
    '✓ Стикер FBS напечатан и наклеен',
  ]
  if (order.requires_marking) {
    lines.push('✓ Честный знак подтверждён WB (проверка перед доставкой)')
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
