const AGENT_FILENAME = 'FulfillmentCRM-PrintAgent.exe'
const INSTALLER_FILENAME = 'install-agent.bat'
const KIOSK_CHROME_FILENAME = 'install-kiosk-chrome.bat'
const KIOSK_CHROME_VBS_FILENAME = 'install-kiosk-chrome.vbs'
const KIOSK_CHROME_MANUAL_FILENAME = 'kiosk-chrome-manual.txt'
export const PRINT_AGENT_DOWNLOAD_URL = `/downloads/${AGENT_FILENAME}`
export const PRINT_AGENT_INSTALLER_URL = `/downloads/${INSTALLER_FILENAME}`
export const KIOSK_CHROME_INSTALLER_URL = `/downloads/${KIOSK_CHROME_FILENAME}`
export const KIOSK_CHROME_VBS_URL = `/downloads/${KIOSK_CHROME_VBS_FILENAME}`
export const KIOSK_CHROME_MANUAL_URL = `/downloads/${KIOSK_CHROME_MANUAL_FILENAME}`

export function buildCrmKioskPrintUrl(origin?: string): string {
  const base = origin ?? (typeof window !== 'undefined' ? window.location.origin : '')
  return `${base}/?print_mode=kiosk`
}

/** Строка для мастера «Создать ярлык» в Windows (Chrome по умолчанию в Program Files). */
export function buildChromeKioskShortcutTarget(origin?: string): string {
  const url = buildCrmKioskPrintUrl(origin)
  return `"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --kiosk-printing ${url}`
}

/** Дополнение к полю «Объект» существующего ярлыка Chrome. */
export function buildChromeKioskShortcutSuffix(origin?: string): string {
  const url = buildCrmKioskPrintUrl(origin)
  return ` --kiosk-printing ${url}`
}
