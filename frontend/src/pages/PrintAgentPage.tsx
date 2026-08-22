import { Link } from 'react-router-dom'
import { PRINT_AGENT_DOWNLOAD_URL } from '../constants/printAgent'
import { refreshPrintBridgeStatus } from '../utils/printService'
import { useEffect, useState } from 'react'
import './PrintAgentPage.css'

export function PrintAgentPage() {
  const [bridgeOk, setBridgeOk] = useState<boolean | null>(null)
  const [printer, setPrinter] = useState('')

  useEffect(() => {
    refreshPrintBridgeStatus().then((health) => {
      setBridgeOk(health.ok)
      setPrinter(health.printer || '')
    })
  }, [])

  return (
    <>
      <header className="topbar">
        <div>
          <h1>Агент печати</h1>
          <p>Локальная программа для Xprinter 365/370 — стикеры FBS без диалога Chrome</p>
        </div>
        <div className="topbar__actions">
          <a className="btn btn--primary" href={PRINT_AGENT_DOWNLOAD_URL} download>
            Скачать агент (.exe)
          </a>
        </div>
      </header>

      <div className="print-agent">
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
              <strong>Агент не найден</strong> — установите и запустите программу на этом ПК
            </p>
          )}
        </section>

        <section className="card print-agent__card">
          <h2>Когда нужен агент</h2>
          <p>
            CRM — это сайт в браузере. Браузер не может напрямую печатать на USB-принтер без подтверждения.
            Агент — небольшая программа на ПК склада, куда подключён Xprinter.
          </p>
          <ul>
            <li>
              <strong>Стикер FBS</strong> после скана — через агент (&lt; 2 сек)
            </li>
            <li>
              <strong>Лист подбора PDF</strong> и <strong>этикетки ячеек</strong> — через Chrome (с подтверждением)
            </li>
          </ul>
        </section>

        <section className="card print-agent__card">
          <h2>Установка (один раз на ПК с принтером)</h2>
          <ol className="print-agent__steps">
            <li>
              Скачайте <a href={PRINT_AGENT_DOWNLOAD_URL} download>«FulfillmentCRM-PrintAgent.exe»</a>
            </li>
            <li>Подключите Xprinter 365 или 370 по USB, установите драйвер</li>
            <li>Запустите агент — появится иконка в трее Windows (синий квадрат FF)</li>
            <li>Включите «Автозапуск Windows» в меню иконки (правый клик)</li>
            <li>
              Откройте <Link to="/assembly">Сборку FBS</Link> — в шапке должно быть «Печать: Xprinter»
            </li>
          </ol>
        </section>

        <section className="card print-agent__card">
          <h2>Настройки принтера</h2>
          <p>
            По умолчанию используется принтер Windows по умолчанию. Чтобы указать Xprinter явно, откройте папку
            настроек из меню трея и отредактируйте <code>config.json</code>:
          </p>
          <pre className="print-agent__code">{`{
  "default_printer": "Xprinter XP-365B",
  "port": 9123
}`}</pre>
          <p className="print-agent__hint">
            Проверка: <a href="http://127.0.0.1:9123/health" target="_blank" rel="noreferrer">http://127.0.0.1:9123/health</a>
          </p>
        </section>
      </div>
    </>
  )
}
