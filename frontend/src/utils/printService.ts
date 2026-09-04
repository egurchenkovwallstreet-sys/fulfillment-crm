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
  openPrintHolder,
  closePrintHolder,
  setPrintHolderMessage,
} from './browserPrint'

export type PrintChannel = 'bridge' | 'browser'
export { openPrintHolder, closePrintHolder, setPrintHolderMessage }

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

/** Печать в заранее открытое окно — только Chrome, без моста (мост закрывает popup). */
async function printFbsStickerInWindow(
  base64: string,
  autoPrint: boolean,
  preopened: Window,
): Promise<PrintChannel> {
  const ok = browserPrintFbsSticker(base64, autoPrint, preopened)
  if (!ok) {
    closePrintHolder(preopened)
    throw new Error('Не удалось открыть печать — разрешите всплывающие окна')
  }
  return 'browser'
}

export async function printFbsSticker(
  base64: string,
  autoPrint = true,
  preopened?: Window | null,
): Promise<PrintChannel> {
  if (preopened && !preopened.closed) {
    return printFbsStickerInWindow(base64, autoPrint, preopened)
  }

  const bridgeAttempt = printViaBridge('fbs_sticker', base64)
  const winner = await Promise.race([
    bridgeAttempt.then((ok) => (ok ? 'bridge' : 'no')),
    new Promise<'no'>((resolve) => {
      window.setTimeout(() => resolve('no'), 400)
    }),
  ])
  if (winner === 'bridge') {
    return 'bridge'
  }
  browserPrintFbsSticker(base64, autoPrint, preopened)
  return 'browser'
}

export async function printSupplySticker(
  base64: string,
  autoPrint = true,
  preopened?: Window | null,
): Promise<PrintChannel> {
  if (preopened && !preopened.closed) {
    return printFbsStickerInWindow(base64, autoPrint, preopened)
  }

  const bridgeAttempt = printViaBridge('supply_sticker', base64)
  const winner = await Promise.race([
    bridgeAttempt.then((ok) => (ok ? 'bridge' : 'no')),
    new Promise<'no'>((resolve) => {
      window.setTimeout(() => resolve('no'), 400)
    }),
  ])
  if (winner === 'bridge') {
    return 'bridge'
  }
  browserPrintSupplySticker(base64, autoPrint, preopened)
  return 'browser'
}
