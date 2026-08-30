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
} from './browserPrint'

export type PrintChannel = 'bridge' | 'browser'
export { openPrintHolder, closePrintHolder }

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

export async function printFbsSticker(
  base64: string,
  autoPrint = true,
  preopened?: Window | null,
): Promise<PrintChannel> {
  const bridgeAttempt = printViaBridge('fbs_sticker', base64)
  const winner = await Promise.race([
    bridgeAttempt.then((ok) => (ok ? 'bridge' : 'no')),
    new Promise<'no'>((resolve) => {
      window.setTimeout(() => resolve('no'), 400)
    }),
  ])
  if (winner === 'bridge') {
    closePrintHolder(preopened)
    return 'bridge'
  }
  browserPrintFbsSticker(base64, autoPrint, preopened)
  return 'browser'
}

export async function printSupplySticker(base64: string, autoPrint = true): Promise<PrintChannel> {
  if (await printViaBridge('supply_sticker', base64)) {
    return 'bridge'
  }
  browserPrintSupplySticker(base64, autoPrint)
  return 'browser'
}
