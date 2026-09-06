const AGENT_FILENAME = 'FulfillmentCRM-PrintAgent.exe'
const INSTALLER_FILENAME = 'install-agent.bat'
const KIOSK_CHROME_FILENAME = 'install-kiosk-chrome.bat'
const KIOSK_CHROME_VBS_FILENAME = 'install-kiosk-chrome.vbs'
export const PRINT_AGENT_DOWNLOAD_URL = `/downloads/${AGENT_FILENAME}`
export const PRINT_AGENT_INSTALLER_URL = `/downloads/${INSTALLER_FILENAME}`
export const KIOSK_CHROME_INSTALLER_URL = `/downloads/${KIOSK_CHROME_FILENAME}`
export const KIOSK_CHROME_VBS_URL = `/downloads/${KIOSK_CHROME_VBS_FILENAME}`

export function buildCrmKioskPrintUrl(origin?: string): string {
  const base = origin ?? (typeof window !== 'undefined' ? window.location.origin : '')
  return `${base}/?print_mode=kiosk`
}
