import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { Link } from 'react-router-dom'
import {
  bindOzonMarking,
  bulkMoveOzonToAssembly,
  bulkShipOzonPostings,
  fetchAssemblySeller,
  fetchBatchRibbon,
  fetchOzonLabel,
  fetchOzonLabelsBulk,
  formOzonAct,
  generateOzonPickList,
  scanOzonBarcode,
  setAssemblyWorkflowMode,
  shipOzonPosting,
  syncOzonAssembly,
  type AssemblyOrder,
  type AssemblySellerDetail,
  type AssemblyWorkflowMode,
} from '../api/assembly'
import { toggleSellerOzonWarehouse, type SellerOzonWarehouse } from '../api/sellers'
import { ApiError } from '../api/client'
import { openPdfBase64 } from '../utils/browserPrint'
import { closePrintHolder, openPrintHolder, printBatchRibbon } from '../utils/batchRibbonPrint'
import { printSupplySticker } from '../utils/printService'
import { BatchBindPanel } from '../components/BatchBindPanel'
import { AssemblySyncOverlay } from '../components/AssemblySyncOverlay'
import { hintWrapProps, uiHint } from '../utils/uiHint'
import { readAssemblySellerCache, writeAssemblySellerCache } from '../utils/assemblyCache'
import './AssemblyPage.css'

const STAGES = [
  { key: 'new', label: 'Новые' },
  { key: 'confirm', label: 'На сборке' },
  { key: 'complete', label: 'В доставке' },
] as const

function stageCount(counts: Record<string, number> | undefined, key: string): number {
  if (key === 'confirm') return counts?.in_picking ?? 0
  if (key === 'complete') return counts?.in_delivery ?? 0
  return counts?.new ?? 0
}

export function OzonAssemblySellerPage({ sellerId }: { sellerId: number }) {
  const scanRef = useRef<HTMLInputElement>(null)
  const [data, setData] = useState<AssemblySellerDetail | null>(
    () => readAssemblySellerCache(sellerId, 'new'),
  )
  const [stage, setStage] = useState('new')
  const [loading, setLoading] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [busyId, setBusyId] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [barcode, setBarcode] = useState('')
  const [pendingMarking, setPendingMarking] = useState<AssemblyOrder | null>(null)
  const [lastCarriageId, setLastCarriageId] = useState<number | null>(null)
  const [togglingId, setTogglingId] = useState<number | null>(null)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(() => new Set())
  const [bulkBusy, setBulkBusy] = useState(false)
  const [ribbonPrinting, setRibbonPrinting] = useState(false)
  const [pickListRefreshing, setPickListRefreshing] = useState(false)
  const skipStageLoad = useRef(true)

  const load = useCallback(async (opts?: { silent?: boolean; stageKey?: string }) => {
    const pickStage = opts?.stageKey ?? stage
    const silent = opts?.silent ?? true
    if (silent) {
      setRefreshing(true)
    } else {
      setLoading(true)
      setError('')
    }
    try {
      const fresh = await fetchAssemblySeller(sellerId, pickStage)
      setData(fresh)
      writeAssemblySellerCache(sellerId, pickStage, fresh)
    } catch (err) {
      if (!silent) {
        setError(err instanceof Error ? err.message : 'Ошибка загрузки')
      }
    } finally {
      if (silent) {
        setRefreshing(false)
      } else {
        setLoading(false)
      }
    }
  }, [sellerId, stage])

  useEffect(() => {
    skipStageLoad.current = true
    let cancelled = false

    const cached = readAssemblySellerCache(sellerId, stage)
    if (cached) setData(cached)

    void (async () => {
      setRefreshing(true)
      try {
        const fromDb = await fetchAssemblySeller(sellerId, stage)
        if (!cancelled) {
          setData(fromDb)
          writeAssemblySellerCache(sellerId, stage, fromDb)
        }
      } catch (err) {
        if (!cancelled && !cached) {
          setError(err instanceof Error ? err.message : 'Ошибка загрузки')
        }
      } finally {
        if (!cancelled) setRefreshing(false)
      }

      setSyncing(true)
      try {
        const synced = await syncOzonAssembly(sellerId, stage)
        if (!cancelled) {
          setData(synced)
          writeAssemblySellerCache(sellerId, stage, synced)
        }
      } catch {
        // Фоновая синхронизация Ozon — оставляем данные из БД
      } finally {
        if (!cancelled) setSyncing(false)
      }
    })()

    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sellerId])

  useEffect(() => {
    if (skipStageLoad.current) {
      skipStageLoad.current = false
      return
    }
    const cached = readAssemblySellerCache(sellerId, stage)
    if (cached) setData(cached)
    void load({ silent: true, stageKey: stage })
  }, [load, sellerId, stage])

  useEffect(() => {
    setSelectedIds(new Set())
  }, [stage])

  useEffect(() => {
    scanRef.current?.focus()
  }, [stage, data?.orders.length, pendingMarking?.id])

  async function handleSync() {
    setSyncing(true)
    setError('')
    setSuccess('')
    try {
      const payload = await syncOzonAssembly(sellerId, stage)
      setData(payload)
      setSuccess('Отправления Ozon обновлены')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка синхронизации Ozon')
    } finally {
      setSyncing(false)
    }
  }

  async function handleScan(e?: FormEvent) {
    e?.preventDefault()
    const value = barcode.trim()
    if (!value) return
    setError('')
    setSuccess('')
    try {
      if (stage === 'confirm' || pendingMarking) {
        const target = pendingMarking || data?.orders.find((item) => item.requires_marking && !item.marking_bound)
        if (!target) {
          setError('Сначала отсканируйте баркод во вкладке «Новые» или нажмите «Скан ЧЗ» в строке')
          return
        }
        const result = await bindOzonMarking(sellerId, target.id, value)
        setSuccess(result.message)
        setBarcode('')
        if (result.action === 'bound') {
          setPendingMarking(null)
        } else {
          setPendingMarking(result.posting)
        }
        await load()
        return
      }
      const result = await scanOzonBarcode(sellerId, value)
      setSuccess(result.message)
      setBarcode('')
      if (result.action === 'await_marking') {
        setPendingMarking(result.posting)
        setStage('confirm')
      }
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Скан не принят')
    } finally {
      scanRef.current?.focus()
    }
  }

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') {
      e.preventDefault()
      void handleScan()
    }
  }

  async function handleBulkToAssembly() {
    const ids = Array.from(selectedIds)
    if (ids.length < 1) return
    setError('')
    setSuccess('')
    setBulkBusy(true)
    try {
      const result = await bulkMoveOzonToAssembly(sellerId, ids)
      setSuccess(result.message)
      setSelectedIds(new Set())
      setStage('confirm')
      setData(await fetchAssemblySeller(sellerId, 'confirm'))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось перевести на сборку')
    } finally {
      setBulkBusy(false)
    }
  }

  async function handleBulkShip() {
    const orders = data?.orders || []
    const ids = orders
      .filter(
        (item) =>
          selectedIds.has(item.id) &&
          (!item.requires_marking || item.marking_bound),
      )
      .map((item) => item.id)
    if (ids.length < 1) {
      setError('Выберите отправления с привязанным ЧЗ (или без маркировки)')
      return
    }
    setError('')
    setSuccess('')
    setBulkBusy(true)
    try {
      const result = await bulkShipOzonPostings(sellerId, ids)
      setSuccess(result.message)
      setSelectedIds(new Set())
      setStage('complete')
      setData(await fetchAssemblySeller(sellerId, 'complete'))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось передать в доставку')
    } finally {
      setBulkBusy(false)
    }
  }

  function toggleSelected(orderId: number) {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(orderId)) next.delete(orderId)
      else next.add(orderId)
      return next
    })
  }

  function selectOurProducts() {
    const ids = (data?.orders || [])
      .filter((item) => item.fulfillment_coverage === 'our')
      .map((item) => item.id)
    setSelectedIds(new Set(ids))
  }

  function toggleSelectAll(checked: boolean) {
    if (!checked) {
      setSelectedIds(new Set())
      return
    }
    setSelectedIds(new Set((data?.orders || []).map((item) => item.id)))
  }

  async function handleShip(order: AssemblyOrder) {
    setError('')
    setSuccess('')
    setBusyId(order.id)
    try {
      const result = await shipOzonPosting(sellerId, order.id)
      setSuccess(result.message)
      setStage('complete')
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось передать к отгрузке')
    } finally {
      setBusyId(null)
    }
  }

  async function handleLabel(order: AssemblyOrder) {
    setError('')
    setSuccess('')
    setBusyId(order.id)
    try {
      const result = await fetchOzonLabel(sellerId, order.id)
      openPdfBase64(result.pdf_base64, result.filename)
      setSuccess(`Этикетка ${order.posting_number} открыта. Напечатайте из окна PDF.`)
    } catch (err) {
      const code = err instanceof ApiError ? err.code : ''
      if (code === 'not_ready') {
        setError('Этикетка ещё готовится. Подождите около минуты после «В доставку» и нажмите ещё раз.')
      } else {
        setError(err instanceof Error ? err.message : 'Не удалось получить этикетку')
      }
    } finally {
      setBusyId(null)
    }
  }

  async function handleLabelsAll() {
    const ids = (data?.orders || []).filter((item) => item.can_print_label).map((item) => item.id)
    if (ids.length < 1) return
    setError('')
    setSuccess('')
    setBusyId(-1)
    try {
      const result = await fetchOzonLabelsBulk(sellerId, ids.slice(0, 20))
      openPdfBase64(result.pdf_base64, result.filename)
      setSuccess(`Открыт PDF с ${result.count ?? ids.length} этикетками`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось получить этикетки')
    } finally {
      setBusyId(null)
    }
  }

  async function handleAct(carriageId?: number) {
    setError('')
    setSuccess('')
    setBusyId(-2)
    try {
      const result = await formOzonAct(sellerId, carriageId)
      const acts = result.acts?.length ? result.acts : [result]
      for (const act of acts) {
        if (act.carriage_id) setLastCarriageId(act.carriage_id)
        if (act.barcode_file) {
          if (act.barcode_file.includes('application/pdf') || act.barcode_file.startsWith('JVBERi0')) {
            openPdfBase64(act.barcode_file, act.filename || 'ozon-barcode.pdf')
          } else {
            await printSupplySticker(act.barcode_file)
          }
        }
        if (act.pdf_base64) {
          openPdfBase64(act.pdf_base64, act.filename || 'ozon-act.pdf')
        }
      }
      setSuccess(result.message || 'Акт сформирован')
      if (acts.some((item) => item.warning)) {
        setError(acts.map((item) => item.warning).filter(Boolean).join(' '))
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось сформировать акт')
    } finally {
      setBusyId(null)
    }
  }

  async function handleWorkflowModeChange(mode: AssemblyWorkflowMode) {
    if (!data) return
    setError('')
    try {
      const result = await setAssemblyWorkflowMode(sellerId, mode)
      setData({ ...data, assembly_workflow_mode: result.assembly_workflow_mode })
      setSuccess(mode === 'batch' ? 'Режим: лента стикеров' : 'Режим: пошаговый скан')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось сменить режим сборки')
    }
  }

  async function handleGenerateOzonPickList() {
    setError('')
    setSuccess('')
    setLoading(true)
    try {
      const result = await generateOzonPickList(sellerId)
      setData((prev) => (prev ? { ...prev, active_pick_list: result.pick_list } : prev))
      setSuccess(`Лист подбора Ozon №${result.pick_list.id}: ${result.pick_list.total_quantity} поз.`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось сформировать лист подбора')
    } finally {
      setLoading(false)
    }
  }

  async function handlePrintBatchRibbon() {
    setError('')
    setSuccess('')
    setRibbonPrinting(true)
    const printWin = openPrintHolder()
    try {
      const result = await fetchBatchRibbon(sellerId)
      const printed = await printBatchRibbon(result.items, true, printWin)
      if (!printed) {
        closePrintHolder(printWin)
        setError('Не удалось открыть печать — разрешите всплывающие окна')
        return
      }
      setSuccess(
        `Лента отправлена на печать: ${result.stickers_count} этикеток в ${result.groups_count} группах`,
      )
    } catch (err) {
      closePrintHolder(printWin)
      setError(err instanceof Error ? err.message : 'Не удалось подготовить ленту')
    } finally {
      setRibbonPrinting(false)
    }
  }

  async function handleToggleWarehouse(warehouse: SellerOzonWarehouse) {
    setTogglingId(warehouse.id)
    setPickListRefreshing(true)
    setError('')
    try {
      await toggleSellerOzonWarehouse(sellerId, warehouse.id, !warehouse.is_enabled)
      const payload = await syncOzonAssembly(sellerId, stage)
      setData(payload)
      if ((data?.assembly_workflow_mode ?? 'scan') === 'batch' && (stage === 'confirm' || stage === 'new')) {
        try {
          const result = await generateOzonPickList(sellerId)
          setData((prev) => (prev ? { ...prev, active_pick_list: result.pick_list } : prev))
        } catch {
          // no postings for pick list yet
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось переключить склад')
    } finally {
      setTogglingId(null)
      setPickListRefreshing(false)
    }
  }

  const warehouses = (data?.warehouses || []) as unknown as SellerOzonWarehouse[]
  const counts = data?.counts
  const orders = data?.orders || []
  const workflowMode: AssemblyWorkflowMode = data?.assembly_workflow_mode ?? 'scan'
  const isBatchMode = workflowMode === 'batch'
  const selectedCount = selectedIds.size
  const allSelected = orders.length > 0 && orders.every((item) => selectedIds.has(item.id))
  const scanOnPicking = stage === 'confirm'
  const scanLabel = scanOnPicking
    ? pendingMarking
      ? `Честный знак для ${pendingMarking.posting_number}`
      : 'Честный знак (DataMatrix)'
    : 'Скан баркода (новые)'

  return (
    <>
      <header className="topbar">
        <div>
          <p>
            <Link to="/assembly" {...uiHint('Вернуться к списку селлеров Ozon для сборки FBS.')}>← Селлеры Ozon</Link>
          </p>
          <h1>{data?.seller.company_name || 'Сборка Ozon'}</h1>
          <p>
            {isBatchMode
              ? 'Лента: лист подбора → печать этикеток → связка баркод + номер отправления (+ ЧЗ)'
              : 'Новые → скан → ЧЗ (если нужен) → в доставку → этикетка PDF → акт/ШК'}
            {syncing ? ' · синхронизация с Ozon…' : ''}
            {refreshing && !syncing ? ' · обновление списка…' : ''}
          </p>
        </div>
        <div className="topbar__actions">
          <div className="assembly-mode-toggle" {...uiHint('Режим 1 — пошаговый скан. Режим 2 — лента стикеров и связка.')}>
            <button
              type="button"
              className={`btn btn--ghost${!isBatchMode ? ' btn--active-mode' : ''}`}
              onClick={() => void handleWorkflowModeChange('scan')}
              disabled={loading || workflowMode === 'scan'}
            >
              Скан
            </button>
            <button
              type="button"
              className={`btn btn--ghost${isBatchMode ? ' btn--active-mode' : ''}`}
              onClick={() => void handleWorkflowModeChange('batch')}
              disabled={loading || workflowMode === 'batch'}
            >
              Лента
            </button>
          </div>
          {stage === 'confirm' && isBatchMode && (
            <>
              <button
                type="button"
                className="btn btn--secondary"
                onClick={() => void handleGenerateOzonPickList()}
                disabled={loading}
              >
                Лист подбора
              </button>
              {data?.active_pick_list && (
                <button
                  type="button"
                  className="btn btn--primary"
                  onClick={() => void handlePrintBatchRibbon()}
                  disabled={loading || ribbonPrinting}
                >
                  {ribbonPrinting ? 'Печать…' : 'Печать ленты'}
                </button>
              )}
            </>
          )}
          <button type="button" className="btn btn--primary" onClick={handleSync} disabled={syncing || loading} {...uiHint('Обновить отправления и счётчики из Ozon для текущей вкладки.')}>
            {syncing ? 'Обновление…' : 'Обновить из Ozon'}
          </button>
        </div>
      </header>

      {error && <div className="alert alert--error">{error}</div>}
      {success && <div className="alert alert--success">{success}</div>}

      {warehouses.length > 0 && (
        <section className="panel">
          <h2 className="section-title">Склады Ozon</h2>
          <div className="assembly-warehouses">
            {warehouses.map((wh) => (
              <label key={wh.id} className="assembly-warehouse">
                <input
                  type="checkbox"
                  checked={wh.is_enabled}
                  disabled={togglingId === wh.id || pickListRefreshing}
                  onChange={() => void handleToggleWarehouse(wh)}
                />
                {wh.name || `Склад #${wh.ozon_warehouse_id}`}
                {wh.is_rfbs ? ' · rFBS' : ''}
              </label>
            ))}
          </div>
        </section>
      )}

      <nav className="assembly-pipeline">
        {STAGES.map((item) => (
          <button
            key={item.key}
            type="button"
            className={`assembly-stage${stage === item.key ? ' assembly-stage--active' : ''}`}
            onClick={() => setStage(item.key)}
            {...uiHint(
              item.key === 'new'
                ? 'Новые отправления — скан баркода для перевода на сборку.'
                : item.key === 'confirm'
                  ? 'На сборке — привязка ЧЗ и передача в доставку.'
                  : 'В доставке — печать этикеток и формирование акта.',
            )}
          >
            <span className="assembly-stage__label">{item.label}</span>
            <span className="assembly-stage__count">{stageCount(counts, item.key)}</span>
          </button>
        ))}
      </nav>

      {(stage === 'new' || stage === 'confirm') && !isBatchMode && (
        <form className="panel assembly-scan-panel" onSubmit={handleScan}>
          <label>
            {scanLabel}
            <input
              ref={scanRef}
              className="assembly-scan-input"
              type="text"
              value={barcode}
              onChange={(e) => setBarcode(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Наведите сканер"
              autoComplete="off"
            />
          </label>
          <button type="submit" className="btn btn--primary" {...uiHint(scanOnPicking ? 'Привязать код «Честный знак» к отправлению на сборке.' : 'Перевести отсканированное отправление на сборку.')}>
            {scanOnPicking ? 'Привязать ЧЗ' : 'На сборку'}
          </button>
        </form>
      )}

      {stage === 'confirm' && isBatchMode && (
        <BatchBindPanel
          sellerId={sellerId}
          disabled={!data?.active_pick_list}
          onBound={() => load()}
          onSuccess={setSuccess}
          onError={setError}
        />
      )}

      {stage === 'complete' && (
        <section className="panel assembly-scan-panel">
          <span {...hintWrapProps('Сформировать акт и штрихкод для сдачи отправлений в пункт Ozon.')}>
            <button
              type="button"
              className="btn btn--primary"
              onClick={() => void handleAct()}
              disabled={busyId === -2 || (data?.orders || []).length === 0}
            >
              {busyId === -2 ? 'Формирование…' : 'Сформировать акт и ШК'}
            </button>
          </span>
          <span {...hintWrapProps('Открыть PDF с этикетками до 20 отправлений для печати.')}>
            <button
              type="button"
              className="btn btn--secondary"
              onClick={() => void handleLabelsAll()}
              disabled={busyId === -1 || (data?.orders || []).length === 0}
            >
              Печать этикеток (до 20)
            </button>
          </span>
          {lastCarriageId ? (
            <button
              type="button"
              className="btn btn--ghost"
              onClick={() => void handleAct(lastCarriageId)}
              disabled={busyId === -2}
              {...uiHint('Повторно сформировать документы для последней отгрузки.')}
            >
              Повторить документы
            </button>
          ) : null}
          <p className="whub-hint">
            Этикетку запрашивайте через минуту после «В доставку». Акт и ШК — для сдачи в пункт Ozon.
          </p>
        </section>
      )}

      <section className="panel">
        {loading && !data && <p>Загрузка…</p>}
        <div className="assembly-ozon-legend">
          <span className="assembly-ozon-legend__item">
            <span className="assembly-ozon-legend__swatch assembly-ozon-legend__swatch--our" aria-hidden />
            Наш товар — принят на фулфилменте, есть ячейка
          </span>
          <span className="assembly-ozon-legend__item">
            <span className="assembly-ozon-legend__swatch assembly-ozon-legend__swatch--unknown" aria-hidden />
            Не наш — артикула нет в CRM или ячейка не создана
          </span>
        </div>
        {(stage === 'new' || stage === 'confirm') && orders.length > 0 && (
          <div className="assembly-ozon-bulk">
            <span className="assembly-ozon-bulk__count">Выбрано: {selectedCount}</span>
            <button
              type="button"
              className="btn btn--ghost btn--small"
              onClick={selectOurProducts}
              {...uiHint('Отметить галочками только строки с нашим товаром (зелёные)')}
            >
              Выбрать наши
            </button>
            <button
              type="button"
              className="btn btn--ghost btn--small"
              onClick={() => setSelectedIds(new Set())}
              disabled={selectedCount === 0}
              {...uiHint('Снять все галочки')}
            >
              Снять выбор
            </button>
            {stage === 'new' && (
              <span {...hintWrapProps('Перевести отмеченные отправления на вкладку «На сборке»')}>
                <button
                  type="button"
                  className="btn btn--primary btn--small"
                  onClick={() => void handleBulkToAssembly()}
                  disabled={bulkBusy || selectedCount === 0}
                >
                  {bulkBusy ? 'Отправка…' : `На сборку (${selectedCount})`}
                </button>
              </span>
            )}
            {stage === 'confirm' && (
              <span {...hintWrapProps('Передать отмеченные отправления в доставку Ozon (нужен ЧЗ, если требуется)')}>
                <button
                  type="button"
                  className="btn btn--primary btn--small"
                  onClick={() => void handleBulkShip()}
                  disabled={bulkBusy || selectedCount === 0}
                >
                  {bulkBusy ? 'Отправка…' : `В доставку (${selectedCount})`}
                </button>
              </span>
            )}
          </div>
        )}
        <table className="assembly-table">
          <thead>
            <tr>
              {(stage === 'new' || stage === 'confirm') && (
                <th className="assembly-table__check">
                  <input
                    type="checkbox"
                    checked={allSelected}
                    onChange={(e) => toggleSelectAll(e.target.checked)}
                    aria-label="Выбрать все"
                    {...uiHint('Выбрать все отправления на странице')}
                  />
                </th>
              )}
              <th>Отправление</th>
              <th>Ячейка</th>
              <th>Баркод</th>
              <th>Товар</th>
              <th>Статус Ozon</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {orders.length === 0 && !loading && (
              <tr>
                <td colSpan={stage === 'new' || stage === 'confirm' ? 7 : 6} className="assembly-table__empty">
                  Нет отправлений в этой вкладке. Нажмите «Обновить из Ozon».
                </td>
              </tr>
            )}
            {orders.map((order) => (
              <tr
                key={order.id}
                className={
                  order.fulfillment_coverage === 'our'
                    ? 'assembly-row--fulfillment-our'
                    : order.fulfillment_coverage === 'unknown'
                      ? 'assembly-row--fulfillment-unknown'
                      : undefined
                }
              >
                {(stage === 'new' || stage === 'confirm') && (
                  <td className="assembly-table__check">
                    <input
                      type="checkbox"
                      checked={selectedIds.has(order.id)}
                      onChange={() => toggleSelected(order.id)}
                      aria-label={`Выбрать ${order.posting_number || order.id}`}
                    />
                  </td>
                )}
                <td>
                  <strong>{order.posting_number || order.id}</strong>
                </td>
                <td>{order.cell_number || '—'}</td>
                <td>{order.barcode}</td>
                <td>
                  {order.product_name || '—'}
                  {order.tech_size ? ` · ${order.tech_size}` : ''}
                  {order.quantity && order.quantity > 1 ? ` · ${order.quantity} шт.` : ''}
                </td>
                <td>{order.wb_status}</td>
                <td className="assembly-table__actions">
                  {stage === 'confirm' && order.requires_marking && !order.marking_bound && (
                    <button
                      type="button"
                      className="btn btn--secondary btn--small"
                      onClick={() => {
                        setPendingMarking(order)
                        scanRef.current?.focus()
                      }}
                      {...uiHint('Перейти к сканированию кода «Честный знак» для этого отправления.')}
                    >
                      Скан ЧЗ
                      {order.marking_needed_count
                        ? ` ${order.marking_bound_count ?? 0}/${order.marking_needed_count}`
                        : ''}
                    </button>
                  )}
                  {stage === 'confirm' && (
                    <span
                      {...hintWrapProps(
                        order.requires_marking && !order.marking_bound
                          ? 'Передать в доставку можно после привязки Честного знака.'
                          : 'Передать отправление в статус «В доставку» в Ozon.',
                      )}
                    >
                      <button
                        type="button"
                        className="btn btn--primary btn--small"
                        onClick={() => void handleShip(order)}
                        disabled={busyId === order.id || (order.requires_marking && !order.marking_bound)}
                      >
                        В доставку
                      </button>
                    </span>
                  )}
                  {order.requires_marking && !order.marking_bound && stage === 'confirm' && (
                    <span className="sellers-tag sellers-tag--warn">нужен ЧЗ</span>
                  )}
                  {stage === 'complete' && (
                    <button
                      type="button"
                      className="btn btn--secondary btn--small"
                      onClick={() => void handleLabel(order)}
                      disabled={busyId === order.id}
                      {...uiHint('Открыть PDF-этикетку отправления для печати.')}
                    >
                      Этикетка
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <AssemblySyncOverlay visible={pickListRefreshing} marketplace="ozon" />
    </>
  )
}
