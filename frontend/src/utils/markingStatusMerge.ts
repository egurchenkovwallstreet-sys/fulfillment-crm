import type { AssemblyOrder, MarkingStatusResult, VerifyMarkingResult } from '../api/assembly'

function patchOrderFromVerify(
  order: AssemblyOrder,
  item: VerifyMarkingResult['results'][number],
): AssemblyOrder {
  if (item.order) {
    return { ...order, ...item.order }
  }
  return {
    ...order,
    marking_verify_status: item.status,
    marking_verify_error: item.error,
    marking_bound: item.marking_bound,
  }
}

function mergeList(
  orders: AssemblyOrder[],
  result: VerifyMarkingResult,
): AssemblyOrder[] {
  const byId = new Map(result.results.map((item) => [item.order_id, item]))
  return orders.map((order) => {
    const item = byId.get(order.id)
    return item ? patchOrderFromVerify(order, item) : order
  })
}

/** Сразу подставить ответ verify/push в панели ЧЗ, не дожидаясь повторного marking-status. */
export function mergeVerifyIntoMarkingStatus(
  prev: MarkingStatusResult,
  result: VerifyMarkingResult | null | undefined,
): MarkingStatusResult {
  if (!result?.results?.length) {
    return prev
  }
  const in_assembly = mergeList(prev.in_assembly, result)
  const ready = mergeList(prev.ready, result)
  const errors = mergeList(prev.errors, result)
  return {
    ...prev,
    in_assembly,
    ready,
    errors,
  }
}
