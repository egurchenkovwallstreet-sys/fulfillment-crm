import type { MarkingVerifyItem, VerifyMarkingResult } from '../api/assembly'

export const MARKING_STATUS_POLL_MS = 5_000
export const MARKING_VERIFY_POLL_MS = 5_000

export function chzStatusLabel(status: string | undefined): string {
  switch ((status || '').trim()) {
    case 'verified':
      return '✓ Принят WB'
    case 'error':
      return '✗ Отклонён'
    case 'pending':
      return '⏳ WB проверяет'
    default:
      return '— Нет данных'
  }
}

export function buildChzVerifyReport(result: VerifyMarkingResult): string {
  if (!result.results.length) {
    return 'WB не вернул статусы по заказам с ЧЗ. Повторите проверку через несколько секунд.'
  }

  const lines = result.results.map((item) => {
    const head = `WB #${item.wb_order_id}: ${chzStatusLabel(item.status)}`
    if (item.status === 'error' && item.error) {
      return `${head}\n${item.error}`
    }
    if (item.status === 'pending') {
      return `${head}\nWB ещё не дал финальный ответ — CRM проверит снова через ~5 секунд.`
    }
    return head
  })

  const verified = result.verified_count ?? result.results.filter((item) => item.status === 'verified').length
  const errors = result.error_count ?? result.results.filter((item) => item.status === 'error').length
  const pending = result.pending_count ?? result.results.filter((item) => item.status === 'pending').length

  const summary = [
    `Принято: ${verified}`,
    `Отклонено: ${errors}`,
    `WB проверяет: ${pending}`,
    '',
    ...lines,
    '',
    'CRM не прекращает проверку сама — опрос каждые 10 секунд, пока WB не ответит «принят» или «отклонён».',
  ]

  return summary.join('\n')
}

export function summarizeChzVerifyResult(result: VerifyMarkingResult): {
  title: string
  tone: 'ok' | 'error' | 'pending'
} {
  const verified = result.verified_count ?? result.results.filter((item) => item.status === 'verified').length
  const errors = result.error_count ?? result.results.filter((item) => item.status === 'error').length
  const pending = result.pending_count ?? result.results.filter((item) => item.status === 'pending').length

  if (!result.results.length) {
    return { title: 'WB не ответил', tone: 'pending' }
  }
  if (errors > 0) {
    return { title: `ЧЗ отклонён: ${errors}`, tone: 'error' }
  }
  if (pending > 0 && verified === 0) {
    return { title: `WB проверяет: ${pending}`, tone: 'pending' }
  }
  if (verified > 0 && pending === 0) {
    return { title: `ЧЗ принят: ${verified}`, tone: 'ok' }
  }
  return {
    title: `Принято ${verified}, WB проверяет ${pending}`,
    tone: pending > 0 ? 'pending' : 'ok',
  }
}

export function pickVerifyItemsForOrder(
  result: VerifyMarkingResult,
  orderId: number,
): MarkingVerifyItem | undefined {
  return result.results.find((item) => item.order_id === orderId)
}
