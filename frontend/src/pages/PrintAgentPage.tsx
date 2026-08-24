import { Link } from 'react-router-dom'
import { PRINT_AGENT_DOWNLOAD_URL } from '../constants/printAgent'
import { refreshPrintBridgeStatus } from '../utils/printService'
import { useEffect, useState } from 'react'
import './PrintAgentPage.css'

export function PrintAgentPage() {
  const [bridgeOk, setBridgeOk] = useState<boolean | null>(null)
  const [printer, setPrinter] = useState('')
  const [bridgeDetail, setBridgeDetail] = useState('')
  const [checking, setChecking] = useState(false)

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
          <button
            type="button"
            className="btn btn--secondary"
            onClick={() => void runHealthCheck()}
            disabled={checking}
          >
            {checking ? 'Проверка…' : 'Проверить снова'}
          </button>
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
              <strong>Агент не найден</strong> — скачайте и запустите программу на этом ПК
              {bridgeDetail ? ` (${bridgeDetail})` : ''}
            </p>
          )}
        </section>

        <section className="card print-agent__card">
          <h2>Установка — 3 шага</h2>
          <ol className="print-agent__steps">
            <li>
              Скачайте <a href={PRINT_AGENT_DOWNLOAD_URL} download>«FulfillmentCRM-PrintAgent.exe»</a> с этой страницы
            </li>
            <li>Подключите принтер по USB (драйвер Windows установится сам или с диска производителя)</li>
            <li>
              Запустите файл — в трее появится синяя иконка <strong>FF</strong>. Готово, ничего настраивать не нужно
            </li>
          </ol>
          <p className="print-agent__hint">
            Агент сам найдёт принтер: сначала тот, что выбран в Windows по умолчанию, иначе Xprinter.
            Другой принтер — правый клик по иконке FF → <strong>Принтер</strong>.
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
            Откройте <Link to="/assembly">Сборку FBS</Link> — в шапке должно быть «Печать: …имя принтера…», не «Chrome».
          </p>
        </section>

        <section className="card print-agent__card">
          <h2>Если не работает</h2>
          <ol className="print-agent__steps">
            <li>Запустите <strong>FulfillmentCRM-PrintAgent.exe</strong> ещё раз</li>
            <li>Если Windows SmartScreen блокирует — «Подробнее» → «Выполнить в любом случае»</li>
            <li>Сделайте нужный принтер <strong>принтером по умолчанию</strong> в Windows (Параметры → Принтеры)</li>
            <li>Или: правый клик по иконке FF → <strong>Принтер</strong> → выберите из списка</li>
            <li>Если иконка исчезает — правый клик FF → <strong>Журнал (agent.log)</strong> и пришлите текст ошибки</li>
          </ol>
        </section>
      </div>
    </>
  )
}
