import {
  bridgePrintImage,
  checkPrintBridge,
  type PrintBridgeHealth,
  type PrintJobType,
} from './printBridge'
import {
  printFbsSticker as browserPrintFbsSticker,
  printSupplySticker as browserPrintSupplySticker,
} from './browserPrint'

export type PrintChannel = 'bridge' | 'browser'

let cachedHealth: PrintBridgeHealth | null = null

export async function refreshPrintBridgeStatus(): Promise<PrintBridgeHealth> {
  cachedHealth = await checkPrintBridge()
  return cachedHealth
}

export function getCachedPrintBridgeHealth(): PrintBridgeHealth | null {
  return cachedHealth
}

async function printViaBridge(jobType: PrintJobType, base64: string): Promise<boolean> {
  if (cachedHealth && !cachedHealth.ok) {
    return false
  }
  try {
    await bridgePrintImage(jobType, base64)
    cachedHealth = { ok: true, ...(cachedHealth || {}) }
    return true
  } catch {
    cachedHealth = { ok: false, detail: 'Ошибка печати через мост' }
    return false
  }
}

export async function printFbsSticker(base64: string, autoPrint = true): Promise<PrintChannel> {
  if (await printViaBridge('fbs_sticker', base64)) {
    return 'bridge'
  }
  browserPrintFbsSticker(base64, autoPrint)
  return 'browser'
}

export async function printSupplySticker(base64: string, autoPrint = true): Promise<PrintChannel> {
  if (await printViaBridge('supply_sticker', base64)) {
    return 'bridge'
  }
  browserPrintSupplySticker(base64, autoPrint)
  return 'browser'
}
