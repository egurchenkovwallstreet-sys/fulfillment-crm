export type StickerLabelOrder = {
  sticker_part_a?: string
  sticker_part_b?: string
}

export function formatStickerNumber(order: StickerLabelOrder | null | undefined): string {
  if (!order) return ''
  const partA = (order.sticker_part_a || '').trim()
  const partB = (order.sticker_part_b || '').trim()
  if (partA && partB) return `${partA} / ${partB}`
  return partA || partB
}

export function appendStickerHint(
  message: string,
  order: StickerLabelOrder | null | undefined,
): string {
  const sticker = formatStickerNumber(order)
  if (!sticker || message.includes(sticker)) return message
  const trimmed = message.trimEnd()
  const suffix = trimmed.endsWith('.') ? '' : '.'
  return `${trimmed}${suffix} Номер стикера: ${sticker}.`
}
