import type { AssemblyOrder } from '../api/assembly'

export type WorkflowStepId = 1 | 2 | 3 | 4

export type ScanPhase = 'barcode' | 'marking'

export const WORKFLOW_STEPS = [
  {
    id: 1 as WorkflowStepId,
    title: 'Лист подбора',
    hint: 'Сформируйте лист и отправьте заказы на сборку в WB',
  },
  {
    id: 2 as WorkflowStepId,
    title: 'Скан баркода',
    hint: 'Сверка с листом подбора и печать стикера FBS',
  },
  {
    id: 3 as WorkflowStepId,
    title: 'Честный знак',
    hint: 'Скан DataMatrix и привязка к заказу в WB',
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
  return order.status === 'label_printed'
    || (order.status === 'marked' && order.marking_bound)
    || order.has_sticker
}

export function orderCanDeliver(order: AssemblyOrder): boolean {
  if (order.can_send_to_delivery) return true
  if ((order.wb_supplier_status || '').trim() !== 'confirm') return false
  if (order.status === 'label_printed') return true
  if (order.status === 'marked' && order.marking_bound) return true
  return false
}

export function orderBlockReason(order: AssemblyOrder): string | null {
  if (orderCanDeliver(order)) return null
  if ((order.wb_supplier_status || '').trim() !== 'confirm') {
    return 'Сначала отправьте заказ на сборку в WB'
  }
  if (!orderStickerPrinted(order)) {
    return 'Отсканируйте баркод и распечатайте стикер FBS'
  }
  if (order.requires_marking && !order.marking_bound) {
    return 'Привяжите Честный знак (DataMatrix)'
  }
  return 'Заказ не готов к доставке'
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
    lines.push('✓ Честный знак привязан в WB')
  }
  lines.push('', 'После подтверждения будет напечатан QR поставки.')
  return lines.join('\n')
}
