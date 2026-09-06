import { Link } from 'react-router-dom'
import {
  PRINT_AGENT_ONE_CLICK_URL,
  PRINT_AGENT_INSTALLER_URL,
  KIOSK_CHROME_INSTALLER_URL,
  KIOSK_CHROME_VBS_URL,
  KIOSK_CHROME_MANUAL_URL,
  buildCrmKioskPrintUrl,
  buildChromeKioskShortcutTarget,
  buildChromeKioskShortcutSuffix,
} from '../constants/printAgent'
import { refreshPrintBridgeStatus } from '../utils/printService'
import { isKioskPrintMode } from '../utils/printMode'
import { copyToClipboard } from '../utils/copyToClipboard'
import { hintWrapProps, uiHint } from '../utils/uiHint'
import { useEffect, useState } from 'react'
import './PrintAgentPage.css'

function CopyLine({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false)

  async function handleCopy() {
    await copyToClipboard(value)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="print-agent__copy-block">
      <p className="print-agent__copy-label">{label}</p>
      <pre className="print-agent__code">{value}</pre>
      <button type="button" className="btn btn--secondary btn--sm" onClick={() => void handleCopy()}>
        {copied ? 'Скопировано' : 'Копировать'}
      </button>
    </div>
  )
}

export function PrintAgentPage() {
  const [bridgeOk, setBridgeOk] = useState<boolean | null>(null)
  const [printer, setPrinter] = useState('')
  const [bridgeDetail, setBridgeDetail] = useState('')
  const [checking, setChecking] = useState(false)
  const kioskMode = isKioskPrintMode()
  const kioskUrl = buildCrmKioskPrintUrl()
  const shortcutTarget = buildChromeKioskShortcutTarget()
  const shortcutSuffix = buildChromeKioskShortcutSuffix()

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
          <p>Один файл — скачать и запустить на ПК склада</p>
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
          <a className="btn btn--primary" href={PRINT_AGENT_ONE_CLICK_URL} download {...uiHint('Скачать один bat — сам скачает агент и установит.')}>
            Скачать и установить (1 файл)
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
              Скачайте <a href={PRINT_AGENT_ONE_CLICK_URL} download>Установить-агент-печати.bat</a>
              {' '}→ запустите двойным щелчком.
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

        <section className="card print-agent__card print-agent__card--hero">
          <h2>ПК склада — 2 шага</h2>
          <ol className="print-agent__steps">
            <li>
              Нажмите <a href={PRINT_AGENT_ONE_CLICK_URL} download><strong>Скачать и установить (1 файл)</strong></a>
            </li>
            <li>
              Дважды щёлкните <strong>Установить-агент-печати.bat</strong> → подождите → «ГОТОВО»
            </li>
          </ol>
          <p className="print-agent__hint">
            Xprinter должен быть <strong>принтером по умолчанию</strong> в Windows.
            Если Windows спрашивает «Разрешить?» — нажмите «Да» / «Выполнить».
          </p>
        </section>

        <section className="card print-agent__card">
          <h2>Сервер (один раз) — скопируйте в консоль Timeweb</h2>
          <CopyLine
            label="Вставьте целиком и нажмите Enter:"
            value="cd /opt/fulfillment-crm && git pull && bash scripts/deploy.sh"
          />
        </section>

        <section className="card print-agent__card print-agent__card--kiosk print-agent__card--secondary">
          <h2>Запасной путь — ярлык Chrome (если агент не ставится)</h2>
          <p>
            Антивирус часто блокирует <code>.bat</code> и <code>.vbs</code> — это ложное срабатывание.
            Надёжнее создать ярлык <strong>вручную</strong> (скрипты не нужны).
          </p>
          <ol className="print-agent__steps">
            <li>
              Сделайте <strong>Xprinter принтером по умолчанию</strong> в Windows (58×40 мм)
            </li>
            <li>
              ПКМ на рабочем столе → <strong>Создать → Ярлык</strong>
            </li>
            <li>
              В поле «Расположение объекта» нажмите «Копировать» и вставьте строку ниже
            </li>
            <li>
              Имя ярлыка: <strong>Fulfillment CRM (autoprint)</strong>
            </li>
            <li>
              Открывайте CRM <strong>только через этот ярлык</strong>, не через обычный Chrome
            </li>
            <li>
              В сборке FBS в шапке: «Печать: Chrome (автопечать)»
            </li>
          </ol>

          <CopyLine label="Строка для нового ярлыка (скопируйте целиком):" value={shortcutTarget} />

          <p className="print-agent__hint">
            Если Chrome не в <code>Program Files</code>, найдите <code>chrome.exe</code> (Пуск → Chrome → ПКМ →
            «Расположение файла») и замените путь в строке. Или откройте свойства существующего ярлыка Chrome
            и в конец поля «Объект» добавьте:
          </p>
          <CopyLine label="Дополнение к полю «Объект» существующего ярлыка Chrome:" value={shortcutSuffix} />

          <details className="print-agent__details">
            <summary>Если антивирус всё же пропускает — скачать установщики</summary>
            <p className="print-agent__hint">
              <a href={KIOSK_CHROME_MANUAL_URL} download>Скачать инструкцию (.txt)</a>
              {' · '}
              <a href={KIOSK_CHROME_INSTALLER_URL} download>install-kiosk-chrome.bat</a>
              {' · '}
              <a href={KIOSK_CHROME_VBS_URL} download>install-kiosk-chrome.vbs</a>
            </p>
            <p className="print-agent__hint">
              При блокировке: Защитник Windows → «Разрешить на устройстве» или добавьте папку «Загрузки» в исключения
              на время установки. URL CRM: <code>{kioskUrl}</code>
            </p>
          </details>
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
              Скачайте <strong>portable.zip</strong> (не один exe) и{' '}
              <a href={PRINT_AGENT_INSTALLER_URL} download>install-agent.bat</a> — bat сам распакует и проверит агент
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
