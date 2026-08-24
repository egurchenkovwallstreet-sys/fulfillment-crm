import {
  bridgePrintImage,
  checkPrintBridge,
  type PrintBridgeHealth,
  type PrintJobType,
} from './printBridge'
import {
  printFbsSticker as browserPrintFbsSticker,
  printSupplySticker as browserPrintSupplySticker,
  openFbsStickerPrintWindow,
} from './browserPrint'

export { openFbsStickerPrintWindow }

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
  try {
    await bridgePrintImage(jobType, base64)
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
  printWindow?: Window | null,
): Promise<PrintChannel> {
  if (await printViaBridge('fbs_sticker', base64)) {
    printWindow?.close()
    return 'bridge'
  }
  browserPrintFbsSticker(base64, autoPrint, printWindow)
  return 'browser'
}

export async function printSupplySticker(base64: string, autoPrint = true): Promise<PrintChannel> {
  if (await printViaBridge('supply_sticker', base64)) {
    return 'bridge'
  }
  browserPrintSupplySticker(base64, autoPrint)
  return 'browser'
}
