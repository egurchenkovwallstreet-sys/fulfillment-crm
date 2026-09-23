import {
  bridgePrintImage,
  checkPrintBridge,
  type PrintBridgeHealth,
  type PrintJobType,
} from './printBridge'
import {
  printFbsSticker as browserPrintFbsSticker,
  printSupplySticker as browserPrintSupplySticker,
  normalizeImageBase64,
  closePrintHolder,
} from './browserPrint'
import { isKioskPrintMode, shouldBrowserAutoPrint } from './printMode'

export type PrintChannel = 'bridge' | 'browser'
export {
  openPrintHolder,
  closePrintHolder,
  blankPrintHolder,
  setPrintHolderMessage,
  warmFbsPrintWindow,
  preloadFbsSticker,
} from './browserPrint'

let cachedHealth: PrintBridgeHealth | null = null

export async function refreshPrintBridgeStatus(): Promise<PrintBridgeHealth> {
  cachedHealth = await checkPrintBridge()
  return cachedHealth
}

export function getCachedPrintBridgeHealth(): PrintBridgeHealth | null {
  return cachedHealth
}

async function printViaBridge(jobType: PrintJobType, base64: string): Promise<boolean> {
  const payload = normalizeImageBase64(base64)
  if (!payload) return false
  try {
    await bridgePrintImage(jobType, payload)
    cachedHealth = { ok: true, ...(cachedHealth || {}) }
    return true
  } catch {
    cachedHealth = await checkPrintBridge()
    return false
  }
}

async function printFbsStickerInWindow(
  base64: string,
  autoPrint: boolean,
  preopened: Window,
  onPrintScheduled?: () => void,
): Promise<PrintChannel> {
  const ok = await browserPrintFbsSticker(base64, autoPrint, preopened, onPrintScheduled)
  if (!ok) {
    closePrintHolder(preopened)
    throw new Error('Не удалось открыть печать — разрешите всплывающие окна')
  }
  return 'browser'
}

/**
 * Стикер заказа FBS.
 * browserOnly=true (сборка): только popup Chrome — один стикер, без гонки с агентом.
 * Иначе: агент если доступен, иначе браузер (ожидаем ответ агента, без параллельной печати).
 */
export async function printFbsSticker(
  base64: string,
  autoPrint = true,
  preopened?: Window | null,
  onPrintScheduled?: () => void,
  browserOnly = false,
): Promise<PrintChannel> {
  const browserAutoPrint = autoPrint && shouldBrowserAutoPrint('fbs_sticker')

  if (
    !browserOnly
    && !isKioskPrintMode()
    && cachedHealth?.ok === true
  ) {
    const ok = await printViaBridge('fbs_sticker', base64)
    if (ok) {
      closePrintHolder(preopened)
      onPrintScheduled?.()
      return 'bridge'
    }
  }

  if (preopened && !preopened.closed) {
    return printFbsStickerInWindow(base64, browserAutoPrint, preopened, onPrintScheduled)
  }

  const ok = await browserPrintFbsSticker(base64, browserAutoPrint, preopened, onPrintScheduled)
  if (!ok) {
    throw new Error('Не удалось открыть печать — разрешите всплывающие окна')
  }
  return 'browser'
}

export async function printSupplySticker(
  base64: string,
  autoPrint = true,
  preopened?: Window | null,
): Promise<PrintChannel> {
  const browserAutoPrint = autoPrint && shouldBrowserAutoPrint('document')

  if (!isKioskPrintMode() && cachedHealth?.ok === true) {
    const bridgeAttempt = printViaBridge('supply_sticker', base64)
    const winner = await Promise.race([
      bridgeAttempt.then((ok) => (ok ? 'bridge' : 'no')),
      new Promise<'no'>((resolve) => {
        window.setTimeout(() => resolve('no'), 800)
      }),
    ])
    if (winner === 'bridge') {
      closePrintHolder(preopened)
      return 'bridge'
    }
  }

  if (preopened && !preopened.closed) {
    return printFbsStickerInWindow(base64, browserAutoPrint, preopened)
  }

  const ok = await browserPrintSupplySticker(base64, browserAutoPrint, preopened)
  if (!ok) {
    throw new Error('Не удалось открыть печать QR поставки')
  }
  return 'browser'
}
