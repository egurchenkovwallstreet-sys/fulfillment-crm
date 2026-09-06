const AGENT_PORTABLE_ZIP = 'FulfillmentCRM-PrintAgent-portable.zip'
const AGENT_ONEFILE = 'FulfillmentCRM-PrintAgent-onefile.exe'
const INSTALLER_FILENAME = 'install-agent.bat'
const KIOSK_CHROME_FILENAME = 'install-kiosk-chrome.bat'
const KIOSK_CHROME_VBS_FILENAME = 'install-kiosk-chrome.vbs'
const KIOSK_CHROME_MANUAL_FILENAME = 'kiosk-chrome-manual.txt'
const AGENT_ONE_CLICK = 'Установить-агент-печати.bat'
export const PRINT_AGENT_ONE_CLICK_URL = `/downloads/${AGENT_ONE_CLICK}`
export const PRINT_AGENT_DOWNLOAD_URL = `/downloads/${AGENT_PORTABLE_ZIP}`
export const PRINT_AGENT_PORTABLE_ZIP_URL = `/downloads/${AGENT_PORTABLE_ZIP}`
export const PRINT_AGENT_ONEFILE_URL = `/downloads/${AGENT_ONEFILE}`
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
