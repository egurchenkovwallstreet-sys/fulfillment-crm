import { useCallback, useEffect, useRef, useState, type ClipboardEvent, type FormEvent, type KeyboardEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  bindMarking,
  deleteAssemblyOrder,
  deletePickList,
  fetchAssemblySeller,
  replaceOrderItem,
  previewPickList,
  reprintOrderSticker,
  scanOrderBarcode,
  sendOrderToAssembly,
  sendOrderToDelivery,
  startAssembly,
  verifyMarking,
  type AssemblyOrder,
  type AssemblySellerDetail,
  type PickList,
  type PrintOrder,
} from '../api/assembly'
import { syncOrders } from '../api/orders'
import { syncSellerWarehouses, toggleSellerWarehouse } from '../api/sellers'
import {
  WORKFLOW_STEPS,
  buildDeliveryConfirmMessage,
  canSwitchToStage,
  orderBlockReason,
  orderCanDeliver,
  resolveWorkflowStep,
  type ScanPhase,
  type StageKey,
} from '../utils/assemblyWorkflow'
import { AssemblyModal, type AssemblyModalState } from '../components/AssemblyModal'
import { ProductPhotoThumb } from '../components/ProductPhotoThumb'
import {
  printFbsSticker,
  printSupplySticker,
  refreshPrintBridgeStatus,
  openFbsStickerPrintWindow,
} from '../utils/printService'
import { downloadPickListPdf } from '../utils/pickListPrint'
import { applyMarkingScanKey, appendPastedMarking } from '../utils/scanMarking'
import './AssemblyPage.css'

const STAGES = [
  { key: 'new', label: 'Новые', tone: 'red' },
  { key: 'confirm', label: 'На сборке', tone: 'orange' },
  { key: 'complete', label: 'В доставке', tone: 'blue' },
] as const

function showAssemblyButton(order: AssemblyOrder): boolean {
  return order.can_send_to_assembly ?? false
}

export function AssemblySellerPage() {
  const { sellerId } = useParams<{ sellerId: string }>()
  const id = Number(sellerId)
  const scanRef = useRef<HTMLInputElement>(null)
  const markingRef = useRef<HTMLInputElement>(null)
  const markingBufferRef = useRef('')

  const [data, setData] = useState<AssemblySellerDetail | null>(null)
  const [stage, setStage] = useState('new')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [scanValue, setScanValue] = useState('')
  const [markingValue, setMarkingValue] = useState('')
  const [scanPhase, setScanPhase] = useState<ScanPhase>('barcode')
  const [pendingOrder, setPendingOrder] = useState<PrintOrder | null>(null)
  const [stickerPreview, setStickerPreview] = useState<string | null>(null)
  const [lastPrinted, setLastPrinted] = useState<AssemblyOrder | null>(null)
  const [syncing, setSyncing] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [togglingWarehouseId, setTogglingWarehouseId] = useState<number | null>(null)
  const initialLoadDoneRef = useRef(false)
  const syncInFlightRef = useRef(false)
  const [bridgeOk, setBridgeOk] = useState<boolean | null>(null)
  const [bridgePrinter, setBridgePrinter] = useState('')
  const [markingErrorOrder, setMarkingErrorOrder] = useState<AssemblyOrder | null>(null)
  const [modal, setModal] = useState<AssemblyModalState | null>(null)
  const [pickListPreview, setPickListPreview] = useState<PickList | null>(null)

  const load = useCallback(async (opts?: { silent?: boolean }) => {
    if (!id) return
    const silent = opts?.silent ?? false
    if (silent) {
      setRefreshing(true)
    } else {
      setLoading(true)
    }
    setError('')
    try {
      setData(await fetchAssemblySeller(id, stage || undefined))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка загрузки')
    } finally {
      if (silent) {
        setRefreshing(false)
      } else {
        setLoading(false)
      }
    }
  }, [id, stage])

  const runBackgroundSync = useCallback(async () => {
    if (!id || syncInFlightRef.current) return
    syncInFlightRef.current = true
    setSyncing(true)
    try {
      await syncOrders(id, 'quick')
      await load({ silent: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка синхронизации с WB')
    } finally {
      syncInFlightRef.current = false
      setSyncing(false)
    }
  }, [id, load])

  useEffect(() => {
    refreshPrintBridgeStatus()
      .then((health) => {
        setBridgeOk(health.ok)
        setBridgePrinter(health.printer || '')
      })
      .catch(() => setBridgeOk(false))
  }, [])

  useEffect(() => {
    if (!id) return
    void load({ silent: initialLoadDoneRef.current })
    initialLoadDoneRef.current = true
  }, [id, stage, load])

  useEffect(() => {
    if (!id) return
    void runBackgroundSync()
  }, [id, runBackgroundSync])

  useEffect(() => {
    if (scanPhase === 'marking') {
      markingBufferRef.current = ''
      setMarkingValue('')
      markingRef.current?.focus()
    } else {
      scanRef.current?.focus()
    }
  }, [scanPhase])

  useEffect(() => {
    if (!id || !data || stage !== 'confirm') return
    const pendingIds = data.orders
      .filter((order) => order.marking_verify_status === 'pending')
      .map((order) => order.id)
    if (pendingIds.length === 0) return

    const refreshPending = async () => {
      try {
        const result = await verifyMarking(id, pendingIds)
        const errored = result.results?.find((item) => item.status === 'error')
        if (errored?.order) {
          setMarkingErrorOrder(errored.order as unknown as AssemblyOrder)
        }
        await load({ silent: true })
      } catch {
        // Фоновый опрос — не перекрываем основной UI ошибками
      }
    }

    void refreshPending()
    const interval = window.setInterval(() => void refreshPending(), 8000)
    return () => window.clearInterval(interval)
  }, [id, data, stage, load])

  useEffect(() => {
    if (!id || stage !== 'complete') return

    const syncDelivery = async () => {
      try {
        await syncOrders(id, 'quick')
        await load({ silent: true })
      } catch {
        // Фоновый опрос вкладки «В доставке»
      }
    }

    void syncDelivery()
    const interval = window.setInterval(() => void syncDelivery(), 5 * 60 * 1000)
    return () => window.clearInterval(interval)
  }, [id, stage, load])

  function resetScanFlow() {
    setScanPhase('barcode')
    setPendingOrder(null)
    markingBufferRef.current = ''
    setMarkingValue('')
    setScanValue('')
    scanRef.current?.focus()
  }

  async function printSticker(base64: string, printWindow?: Window | null) {
    const channel = await printFbsSticker(base64, true, printWindow)
    if (channel === 'bridge') {
      setBridgeOk(true)
    }
    return channel
  }

  async function finishPrint(order: PrintOrder, printWindow?: Window | null) {
    setStickerPreview(order.sticker_file)
    setLastPrinted(order as unknown as AssemblyOrder)
    const channel = await printSticker(order.sticker_file, printWindow)
    const via = channel === 'bridge' ? 'Xprinter (мост)' : 'Chrome'
    const printHint = channel === 'browser' ? ' Нажмите Enter в диалоге печати.' : ''
    setSuccess(
      `Шаг 2: стикер WB #${order.wb_order_id} → ${via}.${printHint} Передайте в доставку (шаг 4).`,
    )
    resetScanFlow()
    setStage('confirm')
  }

  function handleTransferToAssembly() {
    const count = data?.assembly_eligible ?? 0
    if (!id || count < 1) return
    setModal({
      kind: 'confirm',
      title: 'Передать на сборку',
      message:
        `Передать на сборку ${count} заказов в Wildberries?\n\n` +
        'Лист подбора формируется отдельной кнопкой «Сформировать лист подбора».',
      confirmLabel: 'Передать',
      onConfirm: () => void runTransferToAssembly(),
    })
  }

  async function runTransferToAssembly() {
    if (!id) return
    setError('')
    setSuccess('')
    setLoading(true)
    try {
      const result = await startAssembly(id)
      let msg = `Передано на сборку: ${result.orders_count} заказов`
      if (result.wb_assembly_sent != null) {
        msg += `, в WB отправлено ${result.wb_assembly_sent}`
      }
      if (result.wb_assembly_errors?.length) {
        msg += `. Ошибки WB: ${result.wb_assembly_errors.length}`
      }
      if (result.sticker_errors) msg += `. Ошибка стикеров: ${result.sticker_errors}`
      setSuccess(msg)
      setStage('confirm')
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка передачи на сборку')
    } finally {
      setLoading(false)
    }
  }

  function handleDeleteOrder(order: AssemblyOrder) {
    setModal({
      kind: 'confirm',
      title: 'Удалить заказ',
      message:
        `Удалить заказ WB #${order.wb_order_id} из сборки?\n\n` +
        `Баркод: ${order.barcode}\n` +
        'Заказ исчезнет из списка на этой вкладке. В Wildberries статус не меняется.',
      confirmLabel: 'Удалить',
      onConfirm: () => void runDeleteOrder(order.id),
    })
  }

  async function runDeleteOrder(orderId: number) {
    if (!id) return
    setError('')
    setSuccess('')
    setLoading(true)
    try {
      const result = await deleteAssemblyOrder(id, orderId)
      setData((prev) =>
        prev
          ? {
              ...prev,
              counts: { ...prev.counts, ...result.counts },
              assembly_eligible: result.assembly_eligible,
              orders: prev.orders.filter((o) => o.id !== orderId),
            }
          : prev,
      )
      setSuccess(`Заказ WB #${result.order.wb_order_id} удалён из сборки`)
      await load({ silent: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось удалить заказ')
    } finally {
      setLoading(false)
    }
  }

  async function handleGeneratePickList() {
    if (!id) return
    setError('')
    setSuccess('')
    setLoading(true)
    try {
      const result = await previewPickList(id)
      setPickListPreview(result.pick_list)
      const skipped = result.pick_list.orders_skipped
      let msg = `Лист подбора сформирован: ${result.pick_list.total_quantity} заказов`
      if (result.pick_list.warehouse_label) {
        msg += ` (${result.pick_list.warehouse_label})`
      }
      if (skipped) msg += `. Без товара на складе: ${skipped}`
      msg += '. Нажмите «Скачать PDF (A4)».'
      setSuccess(msg)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось сформировать лист подбора')
    } finally {
      setLoading(false)
    }
  }

  function handleDownloadPickListPdf() {
    const pickList = pickListPreview ?? data?.active_pick_list
    if (!pickList) return
    if (!downloadPickListPdf(pickList)) {
      setError('Не удалось открыть PDF — разрешите всплывающие окна в браузере')
    }
  }

  async function handleDeletePickList() {
    if (!id || !data?.active_pick_list) return
    const pickListId = data.active_pick_list.id
    if (!window.confirm(`Удалить лист подбора #${pickListId}? Заказы вернутся в «Новые».`)) {
      return
    }
    setLoading(true)
    setError('')
    try {
      const result = await deletePickList(id, pickListId)
      setSuccess(`Лист подбора #${result.deleted_pick_list_id} удалён (${result.orders_unlocked} зак.)`)
      await load({ silent: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось удалить лист подбора')
    } finally {
      setLoading(false)
    }
  }

  async function handleSyncWarehouses() {
    if (!id) return
    setRefreshing(true)
    setError('')
    try {
      const result = await syncSellerWarehouses(id)
      setSuccess(`Склады WB обновлены: ${result.total} шт.`)
      await load({ silent: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка загрузки складов WB')
    } finally {
      setRefreshing(false)
    }
  }

  async function handleToggleWarehouse(warehouseId: number, isEnabled: boolean) {
    if (!id || !data) return
    const previousWarehouses = data.warehouses
    setData({
      ...data,
      warehouses: data.warehouses.map((wh) => (
        wh.id === warehouseId ? { ...wh, is_enabled: isEnabled } : wh
      )),
    })
    setTogglingWarehouseId(warehouseId)
    setPickListPreview(null)
    setError('')
    setSuccess(isEnabled ? 'Склад включён — обновляем список…' : 'Склад выключен — обновляем список…')
    try {
      await toggleSellerWarehouse(id, warehouseId, isEnabled)
      await load({ silent: true })
      setSuccess(isEnabled ? 'Склад включён' : 'Склад выключен')
      void runBackgroundSync()
    } catch (err) {
      setData((current) => (
        current ? { ...current, warehouses: previousWarehouses } : current
      ))
      setError(err instanceof Error ? err.message : 'Ошибка переключения склада')
    } finally {
      setTogglingWarehouseId(null)
    }
  }

  function requestStageChange(nextStage: StageKey) {
    if (!data) return
    const gate = canSwitchToStage(nextStage, data.counts)
    if (!gate.ok) {
      setModal({ kind: 'block', title: 'Переход заблокирован', message: gate.reason })
      return
    }
    setStage(nextStage)
  }

  async function handleSendToAssembly(orderId: number) {
    if (!id) return
    setError('')
    setSuccess('')
    setLoading(true)
    try {
      const result = await sendOrderToAssembly(id, orderId)
      let msg = `Шаг 1: заказ WB #${result.order.wb_order_id} на сборке в WB`
      if (result.stickers_fetched) msg += ', стикер загружен'
      if (result.sticker_error) msg += `. Ошибка стикера: ${result.sticker_error}`
      setSuccess(msg)
      setStage('confirm')
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка отправки на сборку')
    } finally {
      setLoading(false)
    }
  }

  async function handleSync() {
    if (!id) return
    setError('')
    setSuccess('Обновление заказов…')
    await runBackgroundSync()
    setSuccess('Заказы обновлены')
  }

  function handleSendToDelivery(order: AssemblyOrder) {
    if (!id) return
    if (!orderCanDeliver(order)) {
      setModal({
        kind: 'block',
        title: 'Нельзя передать в доставку',
        message: orderBlockReason(order) || 'Заказ не готов к доставке',
      })
      return
    }
    setModal({
      kind: 'confirm',
      title: 'Передача в доставку WB',
      message: buildDeliveryConfirmMessage(order),
      confirmLabel: 'Подтвердить и печать QR',
      onConfirm: () => void runSendToDelivery(order),
    })
  }

  async function runSendToDelivery(order: AssemblyOrder) {
    if (!id) return
    setError('')
    setSuccess('')
    setLoading(true)
    try {
      const result = await sendOrderToDelivery(id, order.id)
      let msg = `Шаг 4: заказ WB #${result.order.wb_order_id} передан в доставку`
      if (result.stock?.deducted) {
        msg += `. Списано 1 шт., остаток CRM: ${result.stock.quantity} (яч. №${result.stock.cell_number})`
      }
      if (result.supply_barcode_file) {
        const channel = await printSupplySticker(result.supply_barcode_file)
        msg += channel === 'bridge' ? ', QR → Xprinter' : ', QR → Chrome'
      }
      setSuccess(msg)
      setLastPrinted(null)
      setStickerPreview(null)
      setStage('complete')
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка отправки в доставку')
    } finally {
      setLoading(false)
    }
  }

  function handleSendAllReadyToDelivery() {
    if (!data) return
    const ready = data.orders.filter((order) => orderCanDeliver(order))
    if (ready.length === 0) {
      setModal({
        kind: 'block',
        title: 'Нет готовых заказов',
        message: 'Сначала отсканируйте баркоды, распечатайте стикеры FBS и привяжите ЧЗ (если нужен).',
      })
      return
    }
    setModal({
      kind: 'confirm',
      title: 'Массовая передача в доставку',
      message: `Передать в доставку ${ready.length} готовых заказов?\n\nДля каждого будет напечатан QR поставки.`,
      confirmLabel: 'Передать все',
      onConfirm: () => void runSendAllReadyToDelivery(ready),
    })
  }

  async function runSendAllReadyToDelivery(ready: AssemblyOrder[]) {
    if (!data) return
    setError('')
    setSuccess('')
    setLoading(true)
    let delivered = 0
    const errors: string[] = []

    for (const order of ready) {
      try {
        const result = await sendOrderToDelivery(id, order.id)
        delivered += 1
        if (result.supply_barcode_file) {
          await printSupplySticker(result.supply_barcode_file)
        }
      } catch (err) {
        errors.push(err instanceof Error ? err.message : `WB #${order.wb_order_id}`)
      }
    }

    if (delivered > 0) {
      setSuccess(`Шаг 4: передано в доставку ${delivered} из ${ready.length}`)
      setStage('complete')
      await load()
    }
    if (errors.length > 0) {
      setError(errors[0])
    }
    setLoading(false)
  }

  async function handleReprintSticker(orderId: number) {
    if (!id) return
    setLoading(true)
    setError('')
    try {
      const result = await reprintOrderSticker(id, orderId)
      await printSticker(result.order.sticker_file)
      setSuccess(`Стикер заказа WB #${result.order.wb_order_id} отправлен на печать`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось распечатать стикер')
    } finally {
      setLoading(false)
    }
  }

  async function handleBarcodeSubmit(e?: FormEvent) {
    e?.preventDefault()
    if (!id || !scanValue.trim()) return
    const printWindow = openFbsStickerPrintWindow()
    setError('')
    setSuccess('')
    setLoading(true)
    try {
      const result = await scanOrderBarcode(id, scanValue.trim())
      if (result.action === 'await_marking') {
        printWindow?.close()
        setPendingOrder(result.order)
        setScanPhase('marking')
        setScanValue('')
        setSuccess('Шаг 3: отсканируйте код Честного знака (DataMatrix)')
      } else {
        await finishPrint(result.order, printWindow)
      }
      await load()
    } catch (err) {
      printWindow?.close()
      setError(err instanceof Error ? err.message : 'Ошибка сканирования баркода')
    } finally {
      setLoading(false)
      if (scanPhase === 'barcode') scanRef.current?.focus()
    }
  }

  async function handleMarkingSubmit(e?: FormEvent, rawCode?: string) {
    e?.preventDefault()
    const code = (rawCode ?? markingBufferRef.current ?? markingValue).trim()
    if (!id || !pendingOrder || !code) return
    setSuccess('')
    setError('')
    setLoading(true)
    const printWindow = openFbsStickerPrintWindow()
    try {
      const result = await bindMarking(id, pendingOrder.id, code)
      const order = result.order
      if (!printWindow) {
        setError('Разрешите всплывающие окна в Chrome для автоматической печати стикера')
      }
      await finishPrint(order, printWindow)
      if (order.marking_verify_status === 'error') {
        setMarkingErrorOrder(order as unknown as AssemblyOrder)
      }
      await load({ silent: true })
    } catch (err) {
      printWindow?.close()
      setError(err instanceof Error ? err.message : 'Ошибка привязки Честного знака')
      markingRef.current?.focus()
    } finally {
      setLoading(false)
    }
  }

  async function handleReplaceFromErrorModal() {
    if (!id || !markingErrorOrder) return
    setLoading(true)
    setError('')
    try {
      const result = await replaceOrderItem(id, markingErrorOrder.id)
      setSuccess(result.message)
      setMarkingErrorOrder(null)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка замены товара')
    } finally {
      setLoading(false)
    }
  }

  async function handleReplaceOrder() {
    if (!id || !pendingOrder) return
    setLoading(true)
    setError('')
    try {
      const result = await replaceOrderItem(id, pendingOrder.id)
      setSuccess(result.message)
      resetScanFlow()
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка замены товара')
    } finally {
      setLoading(false)
    }
  }

  function handleScanKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') {
      e.preventDefault()
      handleBarcodeSubmit()
    }
  }

  function handleMarkingKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    const result = applyMarkingScanKey(markingBufferRef.current, e)
    if (!result.handled) return
    e.preventDefault()
    markingBufferRef.current = result.next
    setMarkingValue(result.next)
    if (result.submit) void handleMarkingSubmit(undefined, result.next)
  }

  function handleMarkingPaste(e: ClipboardEvent<HTMLInputElement>) {
    e.preventDefault()
    const next = appendPastedMarking(markingBufferRef.current, e.clipboardData.getData('text'))
    markingBufferRef.current = next
    setMarkingValue(next)
  }

  if (!data && loading) {
    return (
      <div className="loading-screen">
        <div className="loading-screen__spinner" />
        <p>Загрузка…</p>
      </div>
    )
  }

  if (!data) return null

  const counts = data.counts
  const assemblyEligible = data.assembly_eligible

  function stageCount(key: string): number {
    if (key === 'confirm') return counts.in_picking ?? 0
    if (key === 'complete') return counts.in_delivery ?? 0
    if (key === 'new') return assemblyEligible ?? counts.new ?? 0
    return counts.new ?? 0
  }

  const ordersBusy = refreshing || syncing || togglingWarehouseId !== null
  const bulkAssemblyCount = assemblyEligible ?? 0
  const displayPickList = pickListPreview ?? data.active_pick_list
  const readyToDeliverCount = data.orders.filter((order) => orderCanDeliver(order)).length
  const currentWorkflowStep = resolveWorkflowStep(
    stage,
    scanPhase,
    readyToDeliverCount > 0 || Boolean(lastPrinted && orderCanDeliver(lastPrinted)),
  )

  return (
    <>
      <header className="topbar">
        <div>
          <p className="assembly-breadcrumb">
            <Link to="/assembly">Сборка FBS</Link> / {data.seller.company_name}
          </p>
          <h1>{data.seller.company_name}</h1>
          <p>
            Полный цикл: лист подбора → скан → стикер → ЧЗ → доставка
            {syncing ? ' · синхронизация с WB…' : ''}
            {refreshing && !syncing ? ' · обновление списка…' : ''}
            {bridgeOk === true && (
              <span className="assembly-bridge assembly-bridge--ok">
                {' '}· Печать: {bridgePrinter || 'Xprinter'}
              </span>
            )}
            {bridgeOk === false && (
              <span className="assembly-bridge assembly-bridge--off">
                {' '}
                · Печать: Chrome (
                <Link to="/print-agent">установите агент</Link>)
              </span>
            )}
          </p>
        </div>
        <div className="topbar__actions">
          <button type="button" className="btn btn--secondary" onClick={handleSync} disabled={loading || syncing || refreshing}>
            Обновить заказы
          </button>
          {stage === 'new' && bulkAssemblyCount > 0 && (
            <>
              <button
                type="button"
                className="btn btn--secondary"
                onClick={() => void handleGeneratePickList()}
                disabled={loading || ordersBusy}
              >
                Сформировать лист подбора
              </button>
              {displayPickList && (
                <button
                  type="button"
                  className="btn btn--secondary"
                  onClick={handleDownloadPickListPdf}
                  disabled={loading}
                >
                  Скачать PDF (A4)
                </button>
              )}
              <button type="button" className="btn btn--primary" onClick={handleTransferToAssembly} disabled={loading}>
                Передать на сборку ({bulkAssemblyCount})
              </button>
            </>
          )}
          {stage !== 'new' && displayPickList && stage !== 'complete' && (
            <button
              type="button"
              className="btn btn--secondary"
              onClick={handleDownloadPickListPdf}
              disabled={loading}
            >
              Скачать PDF (A4)
            </button>
          )}
          {stage === 'confirm' && readyToDeliverCount > 0 && (
            <button type="button" className="btn btn--primary" onClick={handleSendAllReadyToDelivery} disabled={loading}>
              Все готовые в доставку ({readyToDeliverCount})
            </button>
          )}
        </div>
      </header>

      {error && <div className="alert alert--error">{error}</div>}
      {success && <div className="alert alert--success">{success}</div>}

      <section className="assembly-workflow panel">
        <h2 className="section-title">Порядок работы</h2>
        <ol className="assembly-workflow__steps">
          {WORKFLOW_STEPS.map((step) => (
            <li
              key={step.id}
              className={`assembly-workflow__step${currentWorkflowStep === step.id ? ' assembly-workflow__step--active' : ''}${currentWorkflowStep > step.id ? ' assembly-workflow__step--done' : ''}`}
            >
              <span className="assembly-workflow__num">{step.id}</span>
              <div>
                <strong>{step.title}</strong>
                <p>{step.hint}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section className="assembly-pipeline">
        {STAGES.map((s) => {
          const gate = canSwitchToStage(s.key, counts)
          const locked = !gate.ok && stage !== s.key
          return (
          <button
            key={s.key}
            type="button"
            className={`assembly-stage assembly-stage--${s.tone}${stage === s.key ? ' assembly-stage--active' : ''}${locked ? ' assembly-stage--locked' : ''}`}
            onClick={() => requestStageChange(s.key)}
            title={locked ? gate.reason : undefined}
          >
            <span className="assembly-stage__count">{stageCount(s.key)}</span>
            <span className="assembly-stage__label">{s.label}</span>
          </button>
          )
        })}
      </section>

      {stage === 'new' && (
        <section className="panel assembly-step-card assembly-step-card--new">
          <h2 className="section-title">Шаг 1 — подготовка</h2>
          <p>
            Выберите склады WB, нажмите «Сформировать лист подбора» — PDF A4 для печати.
            Отдельно «Передать на сборку» отправляет заказы в Wildberries.
          </p>
        </section>
      )}

      {stage === 'confirm' && scanPhase === 'barcode' && (
        <section className="panel assembly-step-card assembly-step-card--scan">
          <h2 className="section-title">Шаг 2 — сканирование</h2>
          <p>Отсканируйте баркод каждого заказа. Система сверит с листом подбора и напечатает стикер FBS.</p>
        </section>
      )}

      {stage === 'confirm' && readyToDeliverCount > 0 && (
        <section className="panel assembly-step-card assembly-step-card--delivery">
          <h2 className="section-title">Шаг 4 — готово к доставке: {readyToDeliverCount}</h2>
          <p>Стикер напечатан{readyToDeliverCount > 1 ? 'ы' : ''}, ЧЗ привязан (если нужен). Подтвердите передачу в WB.</p>
        </section>
      )}

      <section className="panel assembly-warehouses">
        <div className="assembly-warehouses__header">
          <h2 className="section-title">Точки отгрузки WB</h2>
          <button type="button" className="btn btn--secondary btn--small" onClick={handleSyncWarehouses} disabled={refreshing || syncing}>
            Загрузить из WB
          </button>
        </div>
        <p className="assembly-warehouses__hint">
          Включите только склады вашего фулфилмента. Выключенные склады скрыты из списка заказов.
          {togglingWarehouseId !== null ? ' Сохранение…' : ''}
        </p>
        {data.warehouses.length === 0 ? (
          <p className="assembly-warehouses__empty">Нажмите «Загрузить из WB»</p>
        ) : (
          <ul className="assembly-warehouses__list">
            {data.warehouses.map((wh) => (
              <li key={wh.id} className={wh.is_enabled ? '' : 'assembly-warehouses__item--off'}>
                <label className="assembly-warehouses__toggle">
                  <input
                    type="checkbox"
                    checked={wh.is_enabled}
                    onChange={(e) => void handleToggleWarehouse(wh.id, e.target.checked)}
                    disabled={togglingWarehouseId === wh.id}
                  />
                  <span className="assembly-warehouses__name">{wh.name || `Склад #${wh.wb_warehouse_id}`}</span>
                </label>
                {wh.address && <span className="assembly-warehouses__addr">{wh.address}</span>}
              </li>
            ))}
          </ul>
        )}
      </section>

      <div className="assembly-grid">
        <section className={`panel assembly-orders-panel${ordersBusy ? ' assembly-orders-panel--busy' : ''}`}>
          <h2 className="section-title">
            Заказы ({stageCount(stage)})
            {ordersBusy && <span className="assembly-orders-panel__status">обновление…</span>}
          </h2>
          <table className="assembly-table">
            <thead>
              <tr>
                <th>WB ID</th>
                <th>Баркод</th>
                <th>Фото</th>
                <th>Размер</th>
                <th>Ячейка</th>
                <th>ЧЗ</th>
                <th>Остаток</th>
                <th>Этап</th>
                <th>Стикер</th>
                <th>Действие</th>
              </tr>
            </thead>
            <tbody>
              {data.orders.length === 0 ? (
                <tr>
                  <td colSpan={10} className="assembly-table__empty">Нет заказов на этой вкладке</td>
                </tr>
              ) : data.orders.map((order) => {
                const blockReason = orderBlockReason(order)
                return (
                  <tr key={order.id}>
                    <td>{order.wb_order_id}</td>
                    <td><code>{order.barcode}</code></td>
                    <td>
                      <ProductPhotoThumb
                        url={order.photo_url ?? ''}
                        alt={order.barcode || String(order.wb_order_id)}
                      />
                    </td>
                    <td>
                      <strong className="assembly-order-size">
                        {order.tech_size || '—'}
                      </strong>
                    </td>
                    <td>{order.cell_number || '—'}</td>
                    <td>
                      {order.requires_marking ? (
                        order.marking_verify_status === 'pending' ? (
                          <span className="marking-badge marking-badge--pending" title="Проверка ЧЗ в WB">⏳</span>
                        ) : order.marking_verify_status === 'error' ? (
                          <button
                            type="button"
                            className="marking-badge marking-badge--error"
                            title={order.marking_verify_error || 'ЧЗ отклонён'}
                            onClick={() => setMarkingErrorOrder(order)}
                          >
                            ✕
                          </button>
                        ) : order.marking_bound ? (
                          <span className="marking-badge marking-badge--ok">✓</span>
                        ) : (
                          <span className="marking-badge marking-badge--required">ЧЗ</span>
                        )
                      ) : '—'}
                    </td>
                    <td>
                      {order.warehouse_quantity != null ? (
                        <span className={order.warehouse_quantity < 1 ? 'assembly-stock--low' : ''}>
                          {order.warehouse_quantity} шт.
                        </span>
                      ) : '—'}
                    </td>
                    <td>
                      <div>{order.wb_stage_display || order.status_display}</div>
                      {blockReason && stage === 'confirm' && (
                        <div className="assembly-block-reason">{blockReason}</div>
                      )}
                    </td>
                    <td>
                      {order.has_sticker ? (
                        <button
                          type="button"
                          className="btn btn--small btn--secondary"
                          onClick={() => handleReprintSticker(order.id)}
                          disabled={loading || syncing}
                        >
                          Распечатать
                        </button>
                      ) : '—'}
                    </td>
                    <td className="assembly-table__actions">
                      {showAssemblyButton(order) && stage !== 'complete' && (
                        <button
                          type="button"
                          className="btn btn--small btn--primary"
                          onClick={() => handleSendToAssembly(order.id)}
                          disabled={loading}
                        >
                          На сборку
                        </button>
                      )}
                      {orderCanDeliver(order) && stage === 'confirm' && (
                        <button
                          type="button"
                          className="btn btn--small btn--secondary"
                          onClick={() => handleSendToDelivery(order)}
                          disabled={loading}
                        >
                          В доставку
                        </button>
                      )}
                      <button
                        type="button"
                        className="btn btn--small btn--ghost assembly-order-delete"
                        onClick={() => handleDeleteOrder(order)}
                        disabled={loading}
                        title="Удалить заказ из сборки"
                      >
                        Удалить
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </section>

        <div className="assembly-side">
          {displayPickList && stage !== 'complete' && (
            <section className="panel">
              <div className="assembly-picklist-head">
                <h2 className="section-title">
                  {pickListPreview ? 'Лист подбора (черновик)' : `Лист подбора #${displayPickList.id}`}
                </h2>
                <div className="assembly-picklist-actions">
                  <button type="button" className="btn btn--secondary btn--small" onClick={handleDownloadPickListPdf} disabled={loading}>
                    Скачать PDF (A4)
                  </button>
                  {data.active_pick_list && !pickListPreview && (
                  <button
                    type="button"
                    className="btn btn--secondary btn--small"
                    onClick={handleDeletePickList}
                    disabled={loading}
                  >
                    Удалить лист подбора
                  </button>
                  )}
                </div>
              </div>
              {pickListPreview && (
                <p className="print-agent__hint">
                  Склады: {(pickListPreview as PickList & { warehouse_label?: string }).warehouse_label || 'включённые'}
                  {' · '}{displayPickList.total_quantity} заказов
                </p>
              )}
              <table className="assembly-table pick-list-table">
                <thead>
                  <tr>
                    <th>Ячейка</th>
                    <th>Баркод</th>
                    <th>Кол-во</th>
                  </tr>
                </thead>
                <tbody>
                  {displayPickList.items.map((item) => (
                    <tr key={item.id}>
                      <td><strong>{item.cell_number}</strong></td>
                      <td><code>{item.barcode}</code></td>
                      <td>{item.quantity} шт.</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}

          {stage === 'confirm' && (
            <section className="panel assembly-scan-panel">
              {scanPhase === 'barcode' ? (
                <>
                  <h2 className="section-title">Шаг 2: скан баркода</h2>
                  <p className="assembly-scan-hint">
                    Сверка с листом подбора. Если товар с ЧЗ — после скана откроется шаг 3.
                  </p>
                  <form onSubmit={handleBarcodeSubmit}>
                    <input
                      ref={scanRef}
                      type="text"
                      className="assembly-scan-input"
                      value={scanValue}
                      onChange={(e) => setScanValue(e.target.value)}
                      onKeyDown={handleScanKeyDown}
                      placeholder="Баркод заказа..."
                      autoComplete="off"
                    />
                  </form>
                </>
              ) : (
                <>
                  <h2 className="section-title assembly-scan-panel--marking">Шаг 3: Честный знак</h2>
                  {pendingOrder && (
                    <div className="assembly-pending-order">
                      <p>Заказ WB <strong>#{pendingOrder.wb_order_id}</strong></p>
                      <p>Баркод: <code>{pendingOrder.barcode}</code></p>
                    </div>
                  )}
                  <p className="assembly-scan-hint">
                    Отсканируйте DataMatrix. Код уйдёт в WB, стикер FBS напечатается сразу.
                    Проверка в «Честном знаке» — в фоне (несколько минут); в доставку — только после подтверждения WB.
                  </p>
                  <form onSubmit={handleMarkingSubmit}>
                    <input
                      ref={markingRef}
                      type="text"
                      className="assembly-scan-input assembly-scan-input--marking"
                      value={markingValue}
                      onChange={(e) => {
                        markingBufferRef.current = e.target.value
                        setMarkingValue(e.target.value)
                      }}
                      onKeyDown={handleMarkingKeyDown}
                      onPaste={handleMarkingPaste}
                      placeholder="Код Честного знака (DataMatrix)..."
                      autoComplete="off"
                      autoCapitalize="off"
                      autoCorrect="off"
                      spellCheck={false}
                    />
                  </form>
                  <div className="assembly-scan-actions">
                    <button type="button" className="btn btn--secondary" onClick={handleReplaceOrder} disabled={loading}>
                      Заменить товар
                    </button>
                    <button type="button" className="btn btn--secondary" onClick={resetScanFlow} disabled={loading}>
                      Отмена
                    </button>
                  </div>
                </>
              )}

              {lastPrinted && scanPhase === 'barcode' && orderCanDeliver(lastPrinted) && (
                <div className="assembly-last-print assembly-last-print--ready">
                  <p>
                    <strong>Шаг 4:</strong> WB #{lastPrinted.wb_order_id} готов к доставке
                  </p>
                  <button
                    type="button"
                    className="btn btn--primary btn--small"
                    onClick={() => handleSendToDelivery(lastPrinted)}
                    disabled={loading}
                  >
                    Подтвердить и в доставку
                  </button>
                </div>
              )}

              {stickerPreview && (
                <div className="assembly-sticker-preview">
                  <img src={`data:image/png;base64,${stickerPreview}`} alt="Стикер FBS" />
                  <button type="button" className="btn btn--secondary" onClick={() => void printSticker(stickerPreview)}>
                    Печать ещё раз
                  </button>
                </div>
              )}
            </section>
          )}

          {stage === 'new' && (
            <section className="panel assembly-scan-panel assembly-scan-panel--disabled">
              <h2 className="section-title">Сканирование</h2>
              <p className="assembly-scan-hint">
                Сначала нажмите «Передать на сборку». Затем перейдите на вкладку «На сборке».
              </p>
            </section>
          )}

          {stage === 'complete' && (
            <section className="panel assembly-scan-panel assembly-scan-panel--disabled">
              <h2 className="section-title">Заказы в доставке</h2>
              <p className="assembly-scan-hint">
                Заказы в поставках, ожидающих приёмки на складе WB. Список обновляется каждые 5 минут —
                после сканирования поставки на складе заказы исчезнут отсюда.
              </p>
            </section>
          )}
        </div>
      </div>

      {modal && (
        <AssemblyModal modal={modal} onClose={() => setModal(null)} loading={loading} />
      )}

      {markingErrorOrder && (
        <div className="assembly-marking-modal-backdrop" role="presentation" onClick={() => setMarkingErrorOrder(null)}>
          <div
            className="assembly-marking-modal assembly-marking-modal--error"
            role="alertdialog"
            aria-labelledby="marking-error-title"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 id="marking-error-title">Ошибка проверки Честного знака</h2>
            <p className="assembly-marking-modal__message">
              {markingErrorOrder.marking_verify_error || 'WB отклонил код ЧЗ. Замените товар и отсканируйте другой экземпляр.'}
            </p>
            <dl className="assembly-marking-modal__details">
              <div><dt>Заказ WB</dt><dd>#{markingErrorOrder.wb_order_id}</dd></div>
              <div><dt>Баркод</dt><dd><code>{markingErrorOrder.barcode}</code></dd></div>
              <div><dt>Ячейка</dt><dd>{markingErrorOrder.cell_number || '—'}</dd></div>
            </dl>
            <div className="assembly-marking-modal__actions">
              <button type="button" className="btn btn--primary" onClick={() => void handleReplaceFromErrorModal()} disabled={loading}>
                Заменить товар
              </button>
              <button type="button" className="btn btn--secondary" onClick={() => setMarkingErrorOrder(null)}>
                Закрыть
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

