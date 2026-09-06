import { Link } from 'react-router-dom'
import { PRINT_AGENT_DOWNLOAD_URL, PRINT_AGENT_INSTALLER_URL, KIOSK_CHROME_INSTALLER_URL, KIOSK_CHROME_VBS_URL, buildCrmKioskPrintUrl } from '../constants/printAgent'
import { refreshPrintBridgeStatus } from '../utils/printService'
import { isKioskPrintMode } from '../utils/printMode'
import { hintWrapProps, uiHint } from '../utils/uiHint'
import { useEffect, useState } from 'react'
import './PrintAgentPage.css'

export function PrintAgentPage() {
  const [bridgeOk, setBridgeOk] = useState<boolean | null>(null)
  const [printer, setPrinter] = useState('')
  const [bridgeDetail, setBridgeDetail] = useState('')
  const [checking, setChecking] = useState(false)
  const kioskMode = isKioskPrintMode()
  const kioskUrl = buildCrmKioskPrintUrl()

  async function runHealthCheck() {
    setChecking(true)
    try {
      const health = await refreshPrintBridgeStatus()
      setBridgeOk(health.ok)
      setPrinter(health.printer || '')
      setBridgeDetail(health.detail || '')
    } finally {
      setChecking(false)
    }
  }

  useEffect(() => {
    void runHealthCheck()
  }, [])

  return (
    <>
      <header className="topbar">
        <div>
          <h1>Агент печати</h1>
          <p>Скачайте, запустите — стикеры FBS печатаются без диалога Chrome</p>
        </div>
        <div className="topbar__actions">
          <span {...hintWrapProps('Проверить, запущен ли агент печати на этом компьютере.')}>
            <button
              type="button"
              className="btn btn--secondary"
              onClick={() => void runHealthCheck()}
              disabled={checking}
            >
              {checking ? 'Проверка…' : 'Проверить снова'}
            </button>
          </span>
          <a className="btn btn--primary" href={PRINT_AGENT_DOWNLOAD_URL} download {...uiHint('Скачать программу агента печати для Windows.')}>
            Скачать агент (.exe)
          </a>
          <a className="btn btn--secondary" href={PRINT_AGENT_INSTALLER_URL} download {...uiHint('Скачать bat-установщик — рекомендуемый способ установки агента.')}>
            Установщик (.bat)
          </a>
          <a className="btn btn--secondary" href={KIOSK_CHROME_INSTALLER_URL} download {...uiHint('Bat-установщик — запускает vbs из той же папки.')}>
            Chrome автопечать (.bat)
          </a>
          <a className="btn btn--secondary" href={KIOSK_CHROME_VBS_URL} download {...uiHint('VBS-установщик — можно запустить двойным щелчком без bat.')}>
            Chrome автопечать (.vbs)
          </a>
        </div>
      </header>

      <div className="print-agent">
        {kioskMode && (
          <section className="print-agent__status print-agent__status--ok">
            <p>
              <strong>Режим Chrome автопечати активен</strong> — стикеры FBS должны печататься без Enter
              (открыто через ярлык с <code>--kiosk-printing</code>).
            </p>
          </section>
        )}

        {!kioskMode && bridgeOk === false && (
          <section className="print-agent__status print-agent__status--off">
            <p>
              <strong>Агент не найден.</strong> Без агента или ярлыка Chrome после скана будет диалог печати и Enter.
            </p>
            <p className="print-agent__hint">
              <a href={KIOSK_CHROME_INSTALLER_URL} download>Скачайте install-kiosk-chrome.bat</a>
              {' '}— создаст ярлык <strong>Fulfillment CRM (autoprint)</strong> без установки .exe.
            </p>
          </section>
        )}

        <section className={`print-agent__status print-agent__status--${bridgeOk ? 'ok' : bridgeOk === false ? 'off' : 'unknown'}`}>
          {bridgeOk === null && <p>Проверка агента…</p>}
          {bridgeOk === true && (
            <p>
              <strong>Агент работает</strong>
              {printer ? ` · принтер: ${printer}` : ''}
            </p>
          )}
          {bridgeOk === false && (
            <p>
              <strong>Агент не найден</strong> — скачайте и запустите программу на этом ПК
              {bridgeDetail ? ` (${bridgeDetail})` : ''}
            </p>
          )}
        </section>

        <section className="card print-agent__card print-agent__card--kiosk">
          <h2>Автопечать без агента — Chrome <code>--kiosk-printing</code></h2>
          <p>
            Если агент .exe не ставится: один раз настроить ярлык Chrome — стикеры FBS после скана и ЧЗ
            уходят на принтер <strong>без Enter</strong>.
          </p>
          <ol className="print-agent__steps">
            <li>
              Сделайте <strong>Xprinter принтером по умолчанию</strong> в Windows (58×40 мм, без лишних полей)
            </li>
            <li>
              Скачайте <strong>install-kiosk-chrome.bat</strong> и <strong>install-kiosk-chrome.vbs</strong> в одну папку
              (или только .vbs — запустите двойным щелчком)
            </li>
            <li>
              Запустите bat или vbs — появится ярлык <strong>Fulfillment CRM (autoprint)</strong> на рабочем столе,
              в меню Пуск и в папке загрузки
            </li>
            <li>
              Открывайте CRM <strong>только через этот ярлык</strong>, не через обычный Chrome
            </li>
            <li>
              В сборке FBS в шапке: «Печать: Chrome (автопечать)»
            </li>
          </ol>
          <p className="print-agent__hint">
            Ярлык: <strong>Fulfillment CRM (autoprint)</strong> на рабочем столе и в меню Пуск.
            URL: <code>{kioskUrl}</code>. Другой сервер — откройте bat в блокноте, строка <code>CRM_URL=</code>.
          </p>
        </section>

        <section className="card print-agent__card">
          <h2>Установка агента — рекомендуемый способ</h2>
          <ol className="print-agent__steps">
            <li>
              Скачайте <a href={PRINT_AGENT_DOWNLOAD_URL} download>«FulfillmentCRM-PrintAgent.exe»</a> и{' '}
              <a href={PRINT_AGENT_INSTALLER_URL} download>«install-agent.bat»</a> в одну папку (например, «Загрузки»)
            </li>
            <li>Подключите принтер по USB (драйвер Windows)</li>
            <li>
              Запустите <strong>install-agent.bat</strong> — он скопирует агент в постоянную папку,
              снимет блокировку Windows и проверит, что порт 9123 отвечает
            </li>
            <li>
              Появится окно «Агент запущен» и иконка <strong>FF</strong> в трее (возможно под стрелкой ^)
            </li>
          </ol>
          <p className="print-agent__hint">
            Можно запустить только .exe, но на новом ПК надёжнее через <strong>install-agent.bat</strong>.
            Агент сам найдёт принтер: сначала по умолчанию в Windows, иначе Xprinter.
          </p>
        </section>

        <section className="card print-agent__card">
          <h2>Когда нужен агент</h2>
          <p>
            CRM — сайт в браузере. Браузер не может печатать на USB-принтер без подтверждения.
            Агент — маленькая программа на ПК, куда подключён принтер.
          </p>
          <ul>
            <li>
              <strong>Стикер FBS</strong> после скана ЧЗ — через агент (мгновенно)
            </li>
            <li>
              <strong>Лист подбора PDF</strong> и <strong>этикетки ячеек</strong> — через Chrome (с подтверждением)
            </li>
          </ul>
          <p>
            Откройте <Link to="/assembly" {...uiHint('Перейти к сборке FBS и проверить статус печати в шапке.')}>Сборку FBS</Link> — в шапке должно быть «Печать: …имя принтера…», не «Chrome».
          </p>
        </section>

        <section className="card print-agent__card">
          <h2>Если не устанавливается / не работает</h2>
          <ol className="print-agent__steps">
            <li>
              Используйте <a href={PRINT_AGENT_INSTALLER_URL} download>install-agent.bat</a> — не запускайте exe
              напрямую из «Загрузок» без установщика
            </li>
            <li>Если Windows SmartScreen блокирует — «Подробнее» → «Выполнить в любом случае»</li>
            <li>Антивирус / корпоративная политика — добавьте в исключения:
              <code>%LOCALAPPDATA%\FulfillmentCRM\PrintAgent\</code>
            </li>
            <li>
              Установите{' '}
              <a href="https://aka.ms/vs/17/release/vc_redist.x64.exe" target="_blank" rel="noreferrer">
                Microsoft Visual C++ Redistributable x64
              </a>{' '}
              (если exe сразу закрывается)
            </li>
            <li>Сделайте принтер <strong>по умолчанию</strong> в Windows или: FF в трее → Принтер</li>
            <li>
              Журнал ошибок: <code>%APPDATA%\FulfillmentCRM\PrintAgent\agent.log</code> — пришлите текст,
              если агент не стартует
            </li>
            <li>На странице CRM нажмите «Проверить снова» — должно быть «Агент работает»</li>
          </ol>
        </section>
      </div>
    </>
  )
}
