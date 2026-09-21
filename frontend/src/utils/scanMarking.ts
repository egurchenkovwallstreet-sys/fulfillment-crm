/** Приём DataMatrix Честного знака с USB HID-сканера. */

const GS = '\u001d'

type ScanKeyEvent = {
  key: string
  code?: string
  ctrlKey: boolean
  altKey: boolean
  metaKey: boolean
  keyCode?: number
  which?: number
}

export function isGroupSeparatorKey(e: ScanKeyEvent): boolean {
  if (e.key === GS || e.key === 'F8') return true
  if (e.keyCode === 29 || e.which === 29) return true
  // ASCII 29 (GS) приходит как Ctrl+]
  return Boolean(
    e.ctrlKey &&
      !e.altKey &&
      !e.metaKey &&
      (e.key === ']' || e.code === 'BracketRight'),
  )
}

export function applyMarkingScanKey(
  buffer: string,
  e: ScanKeyEvent & { key: string },
): { next: string; handled: boolean; submit?: boolean } {
  if (e.key === 'Enter') {
    return { next: buffer, handled: true, submit: true }
  }
  if (isGroupSeparatorKey(e)) {
    return { next: buffer + GS, handled: true }
  }
  if (e.key === 'Backspace') {
    return { next: buffer.slice(0, -1), handled: true }
  }
  if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
    return { next: buffer + e.key, handled: true }
  }
  return { next: buffer, handled: false }
}

export function appendPastedMarking(buffer: string, pasted: string): string {
  return buffer + pasted.replace(/\r\n|\r|\n/g, '')
}

const MARKING_MIN_LEN = 16

/** Быстрая проверка до печати — полная валидация остаётся на сервере. */
export function quickMarkingCodeCheck(raw: string): string | null {
  const code = raw.trim()
  if (!code) return 'Код Честного знака пустой — отсканируйте DataMatrix с упаковки'
  if (/[\u0400-\u04FF]/.test(code)) {
    return 'Сканер печатает русскими буквами. Переключите раскладку Windows на ENG и отсканируйте код заново.'
  }
  if (code.length < MARKING_MIN_LEN) {
    return `Код слишком короткий (${code.length} симв.). Проверьте, что сканер считал DataMatrix полностью.`
  }
  return null
}
