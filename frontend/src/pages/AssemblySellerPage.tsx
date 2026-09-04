import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ClipboardEvent, type FormEvent, type KeyboardEvent } from 'react'
import { flushSync } from 'react-dom'
import { Link, useParams } from 'react-router-dom'
import {
  bindMarking,
  deleteAssemblyOrder,
  fetchAssemblySeller,
  fetchBatchRibbon,
  fetchMarkingStatus,
  replaceOrderItem,
  reprintOrderSticker,
  scanOrderBarcode,
  sendOrderToAssembly,
  sendOrderToDelivery,
  fetchSupplyBarcode,
  setAssemblyWorkflowMode,
  startAssembly,
  verifyMarking,
  type AssemblyOrder,
  type AssemblySellerDetail,
  type AssemblyWorkflowMode,
  type PickList,
  type PrintOrder,
  type MarkingStatusResult,
  type SendToDeliveryResult,
} from '../api/assembly'
import { ApiError } from '../api/client'
import { syncOrders, generatePickList } from '../api/orders'
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
import { AssemblyModal, playAssemblyScanErrorBeep, type AssemblyModalState } from '../components/AssemblyModal'
import { BatchBindPanel } from '../components/BatchBindPanel'
import { AssemblySyncOverlay } from '../components/AssemblySyncOverlay'
import {
  AssemblyQueueListModal,
  AssemblyQueuePanels,
  type AssemblyQueuePanelKind,
} from '../components/AssemblyMarkingPanels'
import { ProductPhotoThumb } from '../components/ProductPhotoThumb'
import {
  closePrintHolder,
  openPrintHolder,
  printFbsSticker,
  refreshPrintBridgeStatus,
  setPrintHolderMessage,
  type PrintChannel,
} from '../utils/printService'
import { downloadPickListPdf } from '../utils/pickListPrint'
import { printBatchRibbon } from '../utils/batchRibbonPrint'
import { formatStickerNumber, appendStickerHint } from '../utils/stickerLabel'
import { applyMarkingScanKey, appendPastedMarking } from '../utils/scanMarking'
import { useMarketplace } from '../context/MarketplaceContext'
import { uiHint, hintWrapProps } from '../utils/uiHint'
import { readAssemblySellerCache, writeAssemblySellerCache } from '../utils/assemblyCache'
import { OzonAssemblySellerPage } from './OzonAssemblySellerPage'
import './AssemblyPage.css'

const MARKING_STATUS_POLL_MS = 4000
const MARKING_VERIFY_INITIAL_MS = 3000
const MARKING_VERIFY_INTERVAL_MS = 3000

const EMPTY_MARKING_STATUS: MarkingStatusResult = {
  success: true,
  in_assembly_count: 0,
  ready_count: 0,
  errors_count: 0,
  in_assembly: [],
  ready: [],
  errors: [],
}

const STAGES = [
  { key: 'new', label: 'Новые', tone: 'red' },
  { key: 'confirm', label: 'На сборке', tone: 'orange' },
  { key: 'complete', label: 'В доставке', tone: 'blue' },
] as const

const STAGE_HINTS: Record<(typeof STAGES)[number]['key'], string> = {
  new: 'Новые заказы WB — лист подбора и передача на сборку',
  confirm: 'Скан баркода, ЧЗ и печать стикеров FBS',
  complete: 'Заказы в поставке, ожидают сканирования на складе WB',
}

function showAssemblyButton(order: AssemblyOrder): boolean {
  return order.can_send_to_assembly ?? false
}

function assemblyErrorMessage(
  err: unknown,
  fallback: string,
  contextOrder?: PrintOrder | AssemblyOrder | null,
): string {
  const base = err instanceof Error ? err.message : fallback
  const order =
    err instanceof ApiError && err.order && typeof err.order === 'object'
      ? (err.order as PrintOrder)
      : contextOrder
  return appendStickerHint(base, order ?? undefined)
}

export function AssemblySellerPage() {
  const { sellerId } = useParams<{ sellerId: string }>()
  const { marketplace } = useMarketplace()
  const id = Number(sellerId)
  if (!id) return null
  if (marketplace === 'ozon') {
    return <OzonAssemblySellerPage sellerId={id} />
  }
  return <WbAssemblySellerPage />
}

function WbAssemblySellerPage() {
  const { sellerId } = useParams<{ sellerId: string }>()
  const id = Number(sellerId)
  const scanRef = useRef<HTMLInputElement>(null)
  const markingRef = useRef<HTMLInputElement>(null)
  const scanPanelRef = useRef<HTMLElement>(null)
  const markingBufferRef = useRef('')
  const scanPhaseRef = useRef<ScanPhase>('barcode')
  const markingLockRef = useRef(false)
  const scanBusyRef = useRef(false)
  const barcodeApiInFlightRef = useRef(false)

  const [data, setData] = useState<AssemblySellerDetail | null>(
    () => readAssemblySellerCache(id, 'new'),
  )
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
  const syncInFlightRef = useRef(false)
  const [bridgeOk, setBridgeOk] = useState<boolean | null>(null)
  const [bridgePrinter, setBridgePrinter] = useState('')
  const [markingStatus, setMarkingStatus] = useState<MarkingStatusResult>(EMPTY_MARKING_STATUS)
  const [markingListKind, setMarkingListKind] = useState<AssemblyQueuePanelKind | null>(null)
  const [scanBusy, setScanBusy] = useState(false)
  const verifyInFlightRef = useRef(false)
  const [modal, setModal] = useState<AssemblyModalState | null>(null)
  const [pickListPreview, setPickListPreview] = useState<PickList | null>(null)
  const [ribbonPrinting, setRibbonPrinting] = useState(false)
  const [pickListRefreshing, setPickListRefreshing] = useState(false)
  const bgSyncSellerRef = useRef<number | null>(null)

  const load = useCallback(async (opts?: { silent?: boolean; stageKey?: string }) => {
    if (!id) return
    const pickStage = opts?.stageKey ?? stage
    const silent = opts?.silent ?? true
    if (silent) {
      setRefreshing(true)
    } else {
      setError('')
    }
    try {
      const fresh = await fetchAssemblySeller(id, pickStage || undefined)
      setData(fresh)
      writeAssemblySellerCache(id, pickStage, fresh)
      if (pickStage === 'new' || pickStage === 'confirm') {
        if (fresh.active_pick_list?.items?.length) {
          setPickListPreview(fresh.active_pick_list)
        }
      }
    } catch (err) {
      if (!silent) {
        setError(err instanceof Error ? err.message : 'Ошибка загрузки')
      }
    } finally {
      if (silent) {
        setRefreshing(false)
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
    } catch {
      // Фоновая синхронизация WB — не блокируем экран
    } finally {
      syncInFlightRef.current = false
      setSyncing(false)
    }
  }, [id, load])

  const applySavedPickList = useCallback((fresh: AssemblySellerDetail | null) => {
    if (fresh?.active_pick_list?.items?.length) {
      setPickListPreview(fresh.active_pick_list)
      return
    }
    setPickListPreview(null)
  }, [])

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
    let cancelled = false

    const cached = readAssemblySellerCache(id, stage)
    if (cached) {
      setData(cached)
      applySavedPickList(cached)
    }

    void (async () => {
      setRefreshing(true)
      setError('')
      try {
        const fresh = await fetchAssemblySeller(id, stage || undefined)
        if (cancelled) return
        setData(fresh)
        writeAssemblySellerCache(id, stage, fresh)
        applySavedPickList(fresh)
      } catch (err) {
        if (!cancelled && !cached) {
          setError(err instanceof Error ? err.message : 'Ошибка загрузки')
        }
      } finally {
        if (!cancelled) setRefreshing(false)
      }
    })()

    return () => {
      cancelled = true
    }
  }, [id, stage, applySavedPickList])

  useEffect(() => {
    if (!id) return
    if (bgSyncSellerRef.current === id) return
    bgSyncSellerRef.current = id
    const timer = window.setTimeout(() => {
      void runBackgroundSync()
    }, 500)
    return () => window.clearTimeout(timer)
  }, [id, runBackgroundSync])

  const refreshMarkingStatus = useCallback(async () => {
    if (!id) return
    try {
      setMarkingStatus(await fetchMarkingStatus(id))
    } catch {
      // Фоновое обновление панелей ЧЗ — без алертов
    }
  }, [id])

  const runMarkingVerify = useCallback(async () => {
    if (!id || verifyInFlightRef.current) return
    verifyInFlightRef.current = true
    try {
      await verifyMarking(id)
      await refreshMarkingStatus()
    } catch {
      // Фоновая проверка WB — без алертов во время скана
    } finally {
      verifyInFlightRef.current = false
    }
  }, [id, refreshMarkingStatus])

  useLayoutEffect(() => {
    if (stage !== 'confirm') return
    const inMarking = markingLockRef.current || scanPhase === 'marking' || pendingOrder != null
    if (inMarking) {
      focusMarkingInput()
    } else if (!scanBusy) {
      window.setTimeout(() => scanRef.current?.focus(), 0)
    }
  }, [scanPhase, pendingOrder, scanBusy, stage])

  useEffect(() => {
    if (scanPhase !== 'marking') return
    markingBufferRef.current = ''
    setMarkingValue('')
  }, [scanPhase])

  useEffect(() => {
    if (!id || stage !== 'confirm') return

    void refreshMarkingStatus()
    const statusTimer = window.setInterval(() => void refreshMarkingStatus(), MARKING_STATUS_POLL_MS)

    let verifyInterval: number | undefined
    const verifyBootstrap = window.setTimeout(() => {
      void runMarkingVerify()
      verifyInterval = window.setInterval(
        () => void runMarkingVerify(),
        MARKING_VERIFY_INTERVAL_MS,
      )
    }, MARKING_VERIFY_INITIAL_MS)

    return () => {
      window.clearInterval(statusTimer)
      window.clearTimeout(verifyBootstrap)
      if (verifyInterval) window.clearInterval(verifyInterval)
    }
  }, [id, stage, refreshMarkingStatus, runMarkingVerify])

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

  function normalizeScanCode(value: string): string {
    let code = value.trim().replace(/\s/g, '')
    if (code.endsWith('.0') && /^\d+\.0$/.test(code)) {
      code = code.slice(0, -2)
    }
    return code
  }

  function orderNeedsMarkingScan(order: AssemblyOrder): boolean {
    if (!order.requires_marking) return false
    if (order.marking_verify_status === 'error') return true
    if (order.status === 'label_printed' || order.status === 'marked') return false
    return order.status === 'in_picking' || order.status === 'assembled'
  }

  function openMarkingScan(order: PrintOrder, message?: string) {
    const alreadyOpen = markingLockRef.current && scanPhaseRef.current === 'marking'
    markingLockRef.current = true
    scanPhaseRef.current = 'marking'
    flushSync(() => {
      setScanPhase('marking')
      setPendingOrder(order)
      setScanValue('')
      if (!alreadyOpen) {
        markingBufferRef.current = ''
        setMarkingValue('')
      }
    })
    if (message) setSuccess(message)
    focusMarkingInput()
  }

  function focusMarkingInput() {
    scanPanelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    window.requestAnimationFrame(() => {
      markingRef.current?.focus()
      window.setTimeout(() => markingRef.current?.focus(), 0)
    })
  }

  function resetScanFlow(force = false) {
    if (markingLockRef.current && !force) {
      focusMarkingInput()
      return
    }
    markingLockRef.current = false
    scanPhaseRef.current = 'barcode'
    setScanPhase('barcode')
    setPendingOrder(null)
    markingBufferRef.current = ''
    setMarkingValue('')
    setScanValue('')
    window.setTimeout(() => scanRef.current?.focus(), 0)
  }

  async function printSticker(base64: string, preopened?: Window | null) {
    const payload = (base64 || '').trim()
    if (!payload) {
      closePrintHolder(preopened)
      throw new Error('Стикер пустой — нечего печатать')
    }
    const channel = await printFbsSticker(payload, true, preopened)
    if (channel === 'bridge') {
      setBridgeOk(true)
    }
    return channel
  }

  async function finishPrint(order: PrintOrder, preopened?: Window | null) {
    const file = (order.sticker_file || '').trim()
    if (!file) {
      closePrintHolder(preopened)
      throw new Error(
        `WB не вернул стикер для заказа #${order.wb_order_id}. Обновите заказы или обратитесь к администратору.`,
      )
    }
    setStickerPreview(file)
    setLastPrinted(order as unknown as AssemblyOrder)
    const channel = await printSticker(file, preopened)
    const via = channel === 'bridge' ? 'Xprinter (мост)' : 'Chrome'
    setSuccess(
      `Стикер WB #${order.wb_order_id} → ${via}. Заказ перенесён в «Готовые».`,
    )
    resetScanFlow(true)
    setStage('confirm')
    void refreshMarkingStatus()
  }

  function confirmReprintSticker(order: AssemblyOrder, onDone?: () => void) {
    setModal({
      kind: 'confirm',
      title: 'Повторная печать стикера',
      message:
        `Стикер заказа WB #${order.wb_order_id} уже был напечатан.\n\n` +
        'Печатать повторно только если стикер повреждён или потерян. Продолжить?',
      confirmLabel: 'Печать ещё раз',
      onConfirm: () => void runReprintSticker(order.id, onDone),
    })
  }

  async function runReprintSticker(orderId: number, onDone?: () => void) {
    if (!id) return
    setLoading(true)
    setError('')
    const printWin = openPrintHolder()
    try {
      const result = await reprintOrderSticker(id, orderId, true)
      await printSticker(result.order.sticker_file, printWin)
      setSuccess(`Стикер заказа WB #${result.order.wb_order_id} отправлен на печать`)
      onDone?.()
    } catch (err) {
      closePrintHolder(printWin)
      setError(err instanceof Error ? err.message : 'Не удалось распечатать стикер')
    } finally {
      setLoading(false)
    }
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
      if (result.supplies) {
        msg += `, поставок WB: ${result.supplies}`
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

  async function handleWorkflowModeChange(mode: AssemblyWorkflowMode) {
    if (!id || !data) return
    setError('')
    try {
      const result = await setAssemblyWorkflowMode(id, mode)
      setData({ ...data, assembly_workflow_mode: result.assembly_workflow_mode })
      setSuccess(mode === 'batch' ? 'Режим: лента стикеров' : 'Режим: пошаговый скан')
      resetScanFlow(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось сменить режим сборки')
    }
  }

  async function handlePrintBatchRibbon() {
    if (!id) return
    setError('')
    setSuccess('')
    setRibbonPrinting(true)
    const printWin = openPrintHolder()
    try {
      const result = await fetchBatchRibbon(id)
      if (!result.items?.length) {
        closePrintHolder(printWin)
        setError('В ленте нет стикеров. Сначала сформируйте лист подбора по выбранному складу.')
        return
      }
      const printed = await printBatchRibbon(result.items, true, printWin)
      if (!printed) {
        closePrintHolder(printWin)
        setError('Не удалось открыть печать — разрешите всплывающие окна или установите агент печати')
        return
      }
      setSuccess(
        `Лента отправлена на печать: ${result.stickers_count} стикеров в ${result.groups_count} группах`,
      )
    } catch (err) {
      closePrintHolder(printWin)
      setError(err instanceof Error ? err.message : 'Не удалось подготовить ленту стикеров')
    } finally {
      setRibbonPrinting(false)
    }
  }

  async function handleGeneratePickList() {
    if (!id || !data) return
    const enabled = data.warehouses.some((warehouse) => warehouse.is_enabled)
    if (!enabled) {
      setError('Включите хотя бы один склад FBS — лист подбора строится только по выбранным складам.')
      return
    }
    setError('')
    setSuccess('')
    setPickListRefreshing(true)
    try {
      const pickStage = stage === 'confirm' ? 'confirm' : 'new'
      const pickList = await generatePickList(id, { force: true, stage: pickStage })
      setPickListPreview(pickList)
      setData(await fetchAssemblySeller(id, stage || undefined))
      setSuccess(
        `Лист подбора №${pickList.id}: ${pickList.total_quantity} зак. по выбранным складам. Нажмите «Скачать PDF».`,
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось сформировать лист подбора')
    } finally {
      setPickListRefreshing(false)
    }
  }

  function handleDownloadPickListPdf() {
    const pickList = pickListPreview ?? data?.active_pick_list
    if (!pickList?.items?.length) {
      setError('Сначала нажмите «Сформировать лист подбора» по выбранному складу.')
      return
    }
    if (!downloadPickListPdf(pickList)) {
      setError('Не удалось открыть PDF — разрешите всплывающие окна в браузере')
    }
  }

  async function handleSyncWarehouses() {
    if (!id) return
    setRefreshing(true)
    setError('')
    try {
      const result = await syncSellerWarehouses(id)
      setSuccess(`Склады WB обновлены: ${result.total} шт. После выбора склада нажмите «Сформировать лист подбора».`)
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
    setError('')
    try {
      await toggleSellerWarehouse(id, warehouseId, isEnabled)
      await load({ silent: true })
      setSuccess(
        isEnabled
          ? 'Склад включён. Нажмите «Сформировать лист подбора».'
          : 'Склад выключен. Нажмите «Сформировать лист подбора», если нужен новый список.',
      )
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
    if ((markingLockRef.current || scanPhaseRef.current === 'marking' || pendingOrder) && nextStage !== 'confirm') {
      setModal({
        kind: 'block',
        title: 'Сначала завершите скан ЧЗ',
        message:
          'Сейчас открыт шаг 3 — Честный знак. Отсканируйте DataMatrix или нажмите «Отмена», ' +
          'прежде чем переходить на другую вкладку.',
      })
      return
    }
    const gate = canSwitchToStage(nextStage, counts)
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
    syncInFlightRef.current = true
    setSyncing(true)
    try {
      await syncOrders(id, 'quick')
      await load({ silent: true })
      setSuccess('Заказы обновлены')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка синхронизации с WB')
      setSuccess('')
    } finally {
      syncInFlightRef.current = false
      setSyncing(false)
    }
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
      onConfirm: () => {
        const printWin = openPrintHolder()
        if (!printWin) {
          setError(
            'Не удалось открыть окно печати. Разрешите всплывающие окна для CRM в настройках Chrome.',
          )
          return
        }
        setPrintHolderMessage(printWin, 'Передача в доставку WB…')
        void runSendToDelivery(order, printWin)
      },
    })
  }

  async function resolveSupplyBarcodeFile(
    result: SendToDeliveryResult,
  ): Promise<{ file: string; error?: string }> {
    if (result.supply_barcode_file) {
      return { file: result.supply_barcode_file }
    }
    if (!result.supply_id) {
      return {
        file: '',
        error: result.supply_barcode_error || 'WB не вернул ШК поставки',
      }
    }
    for (let attempt = 0; attempt < 3; attempt += 1) {
      if (attempt > 0) {
        await new Promise((resolve) => window.setTimeout(resolve, 600 * attempt))
      }
      try {
        const retry = await fetchSupplyBarcode(result.supply_id)
        if (retry.supply_barcode_file) {
          return { file: retry.supply_barcode_file }
        }
      } catch {
        // WB иногда отдаёт ШК поставки с задержкой после deliver
      }
    }
    return {
      file: '',
      error: result.supply_barcode_error || 'WB не вернул ШК поставки — попробуйте «Печать QR» в списке поставок',
    }
  }

  async function printSupplyBarcodeAfterDelivery(
    result: SendToDeliveryResult,
    printWin: Window | null,
  ): Promise<{ channel?: PrintChannel; error?: string }> {
    setPrintHolderMessage(printWin, 'Загрузка QR поставки…')
    const { file, error } = await resolveSupplyBarcodeFile(result)
    if (!file) {
      closePrintHolder(printWin)
      return { error }
    }
    try {
      const channel = await printSticker(file, printWin)
      return { channel }
    } catch (err) {
      closePrintHolder(printWin)
      return {
        error: err instanceof Error ? err.message : 'Не удалось отправить QR поставки на печать',
      }
    }
  }

  async function handlePrintSupplyBarcode(supplyId: number, wbSupplyId: string) {
    if (!id) return
    setError('')
    setSuccess('')
    const printWin = openPrintHolder()
    if (!printWin) {
      setError(
        'Не удалось открыть окно печати. Разрешите всплывающие окна для CRM в настройках Chrome.',
      )
      return
    }
    setPrintHolderMessage(printWin, 'Загрузка QR поставки из WB…')
    setLoading(true)
    try {
      const result = await fetchSupplyBarcode(supplyId)
      const file = (result.supply_barcode_file || '').trim()
      if (!file) {
        closePrintHolder(printWin)
        throw new Error('WB не вернул изображение QR поставки')
      }
      const channel = await printSticker(file, printWin)
      const via = channel === 'bridge' ? 'Xprinter' : 'Chrome'
      setSuccess(`QR поставки ${wbSupplyId || result.wb_supply_id} → ${via}`)
    } catch (err) {
      closePrintHolder(printWin)
      setError(err instanceof Error ? err.message : 'Не удалось распечатать QR поставки')
    } finally {
      setLoading(false)
    }
  }

  async function runSendToDelivery(order: AssemblyOrder, printWin: Window | null) {
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
      const printResult = await printSupplyBarcodeAfterDelivery(result, printWin)
      if (printResult.channel) {
        msg += printResult.channel === 'bridge' ? ', QR → Xprinter' : ', QR → Chrome'
      } else if (printResult.error) {
        msg += `. ${printResult.error}`
        setError(printResult.error)
      }
      setSuccess(msg)
      setLastPrinted(null)
      setStickerPreview(null)
      setStage('complete')
      await load()
      await refreshMarkingStatus()
    } catch (err) {
      closePrintHolder(printWin)
      setError(err instanceof Error ? err.message : 'Ошибка отправки в доставку')
    } finally {
      setLoading(false)
    }
  }

  function handleSendAllReadyToDelivery() {
    if (markingQueueBlocked) {
      setModal({
        kind: 'block',
        title: 'Сначала закройте ошибки ЧЗ',
        message:
          'Есть заказы с отклонённым Честным знаком. Откройте панель «Ошибки ЧЗ», ' +
          'замените товар и повторите сборку, затем передавайте в доставку.',
      })
      return
    }
    const ready = markingStatus.ready.filter((order) => orderCanDeliver(order))
    if (ready.length === 0) {
      setModal({
        kind: 'block',
        title: 'Нет готовых заказов',
        message: 'Сначала отсканируйте баркоды и распечатайте стикеры — заказы появятся в «Готовые».',
      })
      return
    }
    setModal({
      kind: 'confirm',
      title: 'Массовая передача в доставку',
      message: `Передать в доставку ${ready.length} готовых заказов?\n\nДля каждого будет напечатан QR поставки.`,
      confirmLabel: 'Передать все',
      onConfirm: () => {
        const printWin = openPrintHolder()
        if (!printWin) {
          setError(
            'Не удалось открыть окно печати. Разрешите всплывающие окна для CRM в настройках Chrome.',
          )
          return
        }
        setPrintHolderMessage(printWin, 'Массовая передача в доставку…')
        void runSendAllReadyToDelivery(ready, printWin)
      },
    })
  }

  async function runSendAllReadyToDelivery(ready: AssemblyOrder[], printWin: Window | null) {
    if (!data) return
    setError('')
    setSuccess('')
    setLoading(true)
    let delivered = 0
    const errors: string[] = []
    const printedSupplyIds = new Set<string>()

    for (const order of ready) {
      try {
        const result = await sendOrderToDelivery(id, order.id)
        delivered += 1
        if (result.wb_supply_id && !printedSupplyIds.has(result.wb_supply_id)) {
          const printResult = await printSupplyBarcodeAfterDelivery(result, printWin)
          if (printResult.channel) {
            printedSupplyIds.add(result.wb_supply_id)
          } else if (printResult.error) {
            errors.push(printResult.error)
          }
        }
      } catch (err) {
        errors.push(err instanceof Error ? err.message : `WB #${order.wb_order_id}`)
      }
    }

    if (printedSupplyIds.size === 0) {
      closePrintHolder(printWin)
    }

    if (delivered > 0) {
      setSuccess(`Шаг 4: передано в доставку ${delivered} из ${ready.length}`)
      setStage('complete')
      await load()
      await refreshMarkingStatus()
    }
    if (errors.length > 0) {
      setError(errors[0])
    }
    setLoading(false)
  }

  async function handleBarcodeSubmit(e?: FormEvent, rawBarcode?: string) {
    e?.preventDefault()
    const barcode = normalizeScanCode(rawBarcode ?? scanRef.current?.value ?? scanValue)
    if (
      !id ||
      !barcode ||
      markingLockRef.current ||
      scanPhaseRef.current === 'marking' ||
      scanBusyRef.current ||
      scanBusy
    ) {
      return
    }

    setError('')
    setSuccess('')
    scanBusyRef.current = true
    barcodeApiInFlightRef.current = true
    setScanBusy(true)
    scanRef.current?.blur()

    try {
      const result = await scanOrderBarcode(id, barcode)
      const needsMarking = result.action === 'await_marking'

      if (needsMarking) {
        openMarkingScan(
          result.order,
          result.message ||
            `Заказ WB #${result.order.wb_order_id} — отсканируйте Честный знак`,
        )
        void refreshMarkingStatus()
        return
      }

      const printWin = openPrintHolder()
      try {
        await finishPrint(result.order, printWin)
      } catch (printErr) {
        closePrintHolder(printWin)
        throw printErr
      }
      void refreshMarkingStatus()
      void load({ silent: true })
    } catch (err) {
      const errOrder =
        err instanceof ApiError && err.order && typeof err.order === 'object'
          ? (err.order as AssemblyOrder)
          : undefined
      const errNeedsMarking = errOrder ? orderNeedsMarkingScan(errOrder) : false
      const keepMarkingUi = markingLockRef.current || errNeedsMarking

      if (keepMarkingUi && errOrder) {
        openMarkingScan(
          errOrder as unknown as PrintOrder,
          `Заказ WB #${errOrder.wb_order_id} — отсканируйте Честный знак`,
        )
      } else {
        resetScanFlow()
      }

      if (err instanceof ApiError && err.code === 'already_printed') {
        void refreshMarkingStatus()
        void load({ silent: true })
        setError(
          err instanceof Error
            ? err.message
            : 'Стикер уже напечатан — заказ в «Готовые».',
        )
        resetScanFlow(true)
        return
      }

      if (err instanceof ApiError && err.code === 'not_in_pick_list') {
        playAssemblyScanErrorBeep()
        setModal({
          kind: 'scan-error',
          title: 'Ошибка',
          message: 'Баркода нет в листе подбора!',
          onDismiss: () => {
            if (keepMarkingUi || markingLockRef.current) {
              focusMarkingInput()
            } else {
              resetScanFlow()
            }
          },
        })
        if (keepMarkingUi || markingLockRef.current) {
          setError('Баркода нет в листе подбора! Обновите лист подбора или проверьте штрихкод.')
          focusMarkingInput()
        }
        return
      }
      setError(assemblyErrorMessage(err, 'Ошибка сканирования баркода'))
      if (keepMarkingUi || markingLockRef.current) {
        focusMarkingInput()
      } else {
        scanRef.current?.focus()
      }
    } finally {
      barcodeApiInFlightRef.current = false
      scanBusyRef.current = false
      setScanBusy(false)
    }
  }

  async function handleMarkingSubmit(e?: FormEvent, rawCode?: string) {
    e?.preventDefault()
    const code = (rawCode ?? markingBufferRef.current ?? markingValue).trim()
    if (!id || !pendingOrder || !code || scanBusyRef.current) return
    setSuccess('')
    setError('')
    scanBusyRef.current = true
    setScanBusy(true)
    const printWin = openPrintHolder()
    try {
      const started = Date.now()
      while (barcodeApiInFlightRef.current && Date.now() - started < 15000) {
        await new Promise((resolve) => window.setTimeout(resolve, 40))
      }
      const result = await bindMarking(id, pendingOrder.id, code)
      await finishPrint(result.order, printWin)
      window.setTimeout(() => void runMarkingVerify(), MARKING_VERIFY_INITIAL_MS)
      void refreshMarkingStatus()
      void load({ silent: true })
    } catch (err) {
      closePrintHolder(printWin)
      if (err instanceof ApiError && err.code === 'already_printed') {
        void refreshMarkingStatus()
        void load({ silent: true })
        resetScanFlow(true)
      }
      setError(assemblyErrorMessage(err, 'Ошибка привязки Честного знака', pendingOrder))
      focusMarkingInput()
    } finally {
      scanBusyRef.current = false
      setScanBusy(false)
    }
  }

  async function handleReplaceOrderFromList(order: AssemblyOrder) {
    if (!id) return
    setLoading(true)
    setError('')
    try {
      const result = await replaceOrderItem(id, order.id)
      setSuccess(result.message)
      setMarkingListKind(null)
      await refreshMarkingStatus()
      await load({ silent: true })
    } catch (err) {
      setError(assemblyErrorMessage(err, 'Ошибка замены товара', order))
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
      resetScanFlow(true)
      await refreshMarkingStatus()
      await load({ silent: true })
    } catch (err) {
      setError(assemblyErrorMessage(err, 'Ошибка замены товара', pendingOrder))
    } finally {
      setLoading(false)
    }
  }

  function handleScanKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') {
      e.preventDefault()
      if (scanBusyRef.current || markingLockRef.current || scanPhaseRef.current === 'marking') return
      const value = e.currentTarget.value
      e.currentTarget.blur()
      void handleBarcodeSubmit(undefined, value)
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

  const workflowMode: AssemblyWorkflowMode = data?.assembly_workflow_mode ?? 'scan'
  const isBatchMode = workflowMode === 'batch'

  const counts = data?.counts ?? {}
  const assemblyEligible = data?.assembly_eligible
  const sellerName = data?.seller.company_name ?? 'Сборка FBS'

  function stageCount(key: string): number {
    if (key === 'confirm') return counts.in_picking ?? 0
    if (key === 'complete') return counts.in_delivery ?? 0
    if (key === 'new') return assemblyEligible ?? counts.new ?? 0
    return counts.new ?? 0
  }

  const ordersBusy = refreshing || syncing || togglingWarehouseId !== null
  const bulkAssemblyCount = assemblyEligible ?? 0
  const displayPickList = pickListPreview ?? data?.active_pick_list
  const orders = data?.orders ?? []
  const deliverySupplies = data?.delivery_supplies ?? []
  const readyOrders = markingStatus.ready
  const readyToDeliverCount = readyOrders.filter((order) => orderCanDeliver(order)).length
  const markingQueueBlocked = stage === 'confirm' && markingStatus.errors_count > 0
  const markingInProgress = scanPhase === 'marking' || Boolean(pendingOrder)
  const currentWorkflowStep = resolveWorkflowStep(
    stage,
    scanPhase,
    !markingInProgress &&
      (readyToDeliverCount > 0 || Boolean(lastPrinted && orderCanDeliver(lastPrinted))),
  )
  const markingListOrders =
    markingListKind === 'errors'
      ? markingStatus.errors
      : markingListKind === 'ready'
        ? markingStatus.ready
        : markingListKind === 'in_assembly'
          ? markingStatus.in_assembly
          : []

  return (
    <>
      <header className="topbar">
        <div>
          <p className="assembly-breadcrumb">
            <Link to="/assembly">Сборка FBS</Link> / {sellerName}
          </p>
          <h1>{sellerName}</h1>
          <p>
            {isBatchMode
              ? 'Режим ленты: сформируйте лист подбора → «Печать ленты стикеров» → связка баркод + стикер.'
              : 'Режим скана: сформируйте лист подбора по складу → скачайте PDF → скан баркода → ЧЗ → печать стикера.'}
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
          <button
            type="button"
            className="btn btn--secondary"
            onClick={handleSync}
            disabled={loading || syncing || refreshing}
            {...uiHint('Подтянуть новые заказы и статусы из Wildberries')}
          >
            Обновить заказы
          </button>
          {(stage === 'new' || stage === 'confirm') && (
            <button
              type="button"
              className={`btn ${!isBatchMode ? 'btn--primary' : 'btn--secondary'}`}
              onClick={() => void handleGeneratePickList()}
              disabled={loading || pickListRefreshing || togglingWarehouseId !== null}
              {...uiHint('Собрать лист подбора только по включённым складам FBS текущей вкладки')}
            >
              {pickListRefreshing ? 'Формируем…' : 'Сформировать лист подбора'}
            </button>
          )}
          {(stage === 'new' || stage === 'confirm') && displayPickList?.items?.length ? (
            <button
              type="button"
              className="btn btn--secondary"
              onClick={handleDownloadPickListPdf}
              disabled={loading || pickListRefreshing}
              {...uiHint('Скачать лист подбора формата A4 для печати')}
            >
              Скачать PDF (A4) · {displayPickList.total_quantity} зак.
            </button>
          ) : null}
          {stage === 'new' && bulkAssemblyCount > 0 && (
            <button
              type="button"
              className="btn btn--primary"
              onClick={handleTransferToAssembly}
              disabled={loading}
              {...uiHint('Отправить выбранные новые заказы в статус «На сборке» в WB')}
            >
              Передать на сборку ({bulkAssemblyCount})
            </button>
          )}
          {stage === 'confirm' && isBatchMode && (displayPickList || data?.active_pick_list) && (
            <button
              type="button"
              className="btn btn--primary"
              onClick={() => void handlePrintBatchRibbon()}
              disabled={loading || ribbonPrinting || ordersBusy}
              {...uiHint('Печать ленты 58×40: инфо-стикер перед каждым баркодом, затем стикеры заказов')}
            >
              {ribbonPrinting ? 'Печать…' : 'Печать ленты стикеров'}
            </button>
          )}
          {stage === 'confirm' && readyToDeliverCount > 0 && (
            <span
              {...hintWrapProps(
                markingQueueBlocked
                  ? 'Сначала закройте ошибки ЧЗ'
                  : 'Передать все собранные заказы из «Готовые» в доставку WB',
              )}
            >
              <button
                type="button"
                className="btn btn--primary"
                onClick={handleSendAllReadyToDelivery}
                disabled={loading || markingQueueBlocked}
              >
                Все готовые в доставку ({readyToDeliverCount})
              </button>
            </span>
          )}
        </div>
      </header>

      {error && <div className="alert alert--error">{error}</div>}
      {!data && (refreshing || syncing) && !error && (
        <div className="alert alert--success">Загружаем данные селлера…</div>
      )}
      {!data && !refreshing && !syncing && error && (
        <div className="panel">
          <p>Не удалось загрузить кабинет сборки.</p>
          <button type="button" className="btn btn--primary" onClick={() => void load({ silent: false, stageKey: stage })}>
            Повторить
          </button>
        </div>
      )}
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

      {stage === 'confirm' && (
        <AssemblyQueuePanels
          inAssemblyCount={markingStatus.in_assembly_count}
          readyCount={markingStatus.ready_count}
          errorsCount={markingStatus.errors_count}
          onOpenList={setMarkingListKind}
        />
      )}

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
            {...uiHint(locked ? gate.reason : STAGE_HINTS[s.key])}
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
            Выберите склады FBS и нажмите «Сформировать лист подбора», затем «Скачать PDF».
            «Передать на сборку» отдельно отправляет заказы в Wildberries.
          </p>
        </section>
      )}

      {stage === 'confirm' && isBatchMode && (
        <BatchBindPanel
          sellerId={id}
          disabled={!data?.active_pick_list}
          onBound={async () => {
            window.setTimeout(() => void runMarkingVerify(), MARKING_VERIFY_INITIAL_MS)
            await refreshMarkingStatus()
            await load({ silent: true })
          }}
          onSuccess={setSuccess}
          onError={setError}
        />
      )}

      {stage === 'confirm' && !isBatchMode && (
        <section
          ref={scanPanelRef}
          className={`panel assembly-scan-panel assembly-scan-live${markingInProgress ? ' assembly-scan-panel--marking-active' : ''}`}
        >
          {!markingInProgress ? (
            <div>
              <h2 className="section-title">Сканируйте баркод заказа</h2>
              <p className="assembly-scan-hint">
                Курсор уже в поле. Сначала «Сформировать лист подбора» и «Скачать PDF» в шапке.
                После скана товара с ЧЗ сразу откроется окно DataMatrix, затем печать стикера.
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
                  autoFocus
                  disabled={scanBusy}
                />
              </form>
            </div>
          ) : (
            <div>
              <h2 className="section-title assembly-scan-panel--marking">Сканируйте Честный знак</h2>
              {pendingOrder && (
                <div className="assembly-pending-order">
                  <p>Заказ WB <strong>#{pendingOrder.wb_order_id}</strong></p>
                  <p>Баркод: <code>{pendingOrder.barcode}</code></p>
                  {formatStickerNumber(pendingOrder) && (
                    <p className="assembly-pending-order__sticker">
                      Номер стикера: <strong>{formatStickerNumber(pendingOrder)}</strong>
                    </p>
                  )}
                </div>
              )}
              <p className="assembly-scan-hint">
                DataMatrix с упаковки. Код привяжется к заказу в WB, стикер FBS отправится на печать сразу.
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
                  autoFocus
                />
              </form>
              <div className="assembly-scan-actions">
                <button
                  type="button"
                  className="btn btn--secondary"
                  onClick={handleReplaceOrder}
                  disabled={loading}
                  {...uiHint('Снять заказ и подставить другой товар с тем же баркодом')}
                >
                  Заменить товар
                </button>
                <button
                  type="button"
                  className="btn btn--secondary"
                  onClick={() => resetScanFlow(true)}
                  disabled={loading}
                  {...uiHint('Вернуться к сканированию баркода без привязки ЧЗ')}
                >
                  Отмена
                </button>
              </div>
            </div>
          )}

          {lastPrinted && !markingInProgress && orderCanDeliver(lastPrinted) && (
            <div className="assembly-last-print assembly-last-print--ready">
              <p>
                <strong>Шаг 4:</strong> WB #{lastPrinted.wb_order_id} готов к доставке
              </p>
              <span
                {...hintWrapProps(
                  markingQueueBlocked
                    ? 'Сначала закройте ошибки ЧЗ'
                    : 'Добавить заказ в поставку WB и перевести в доставку',
                )}
              >
                <button
                  type="button"
                  className="btn btn--primary btn--small"
                  onClick={() => handleSendToDelivery(lastPrinted)}
                  disabled={loading || markingQueueBlocked}
                >
                  Подтвердить и в доставку
                </button>
              </span>
            </div>
          )}

          {stickerPreview && (
            <div className="assembly-sticker-preview">
              <img src={`data:image/png;base64,${stickerPreview}`} alt="Стикер FBS" />
            </div>
          )}
        </section>
      )}

      {stage === 'confirm' && readyToDeliverCount > 0 && !markingInProgress && (
        <section className="panel assembly-step-card assembly-step-card--delivery">
          <h2 className="section-title">Шаг 4 — готово к доставке: {readyToDeliverCount}</h2>
          <p>
            Заказы в «Готовые» ({markingStatus.ready_count}). Подтвердите передачу в WB — список
            открывается по зелёному счётчику.
          </p>
        </section>
      )}

      <section className="panel assembly-warehouses">
        <div className="assembly-warehouses__header">
          <h2 className="section-title">Точки отгрузки WB</h2>
          <button
            type="button"
            className="btn btn--secondary btn--small"
            onClick={handleSyncWarehouses}
            disabled={refreshing || syncing}
            {...uiHint('Загрузить список FBS-складов селлера из Wildberries')}
          >
            Загрузить из WB
          </button>
        </div>
        <p className="assembly-warehouses__hint">
          Включите склады вашего фулфилмента. Количество заказов обновится сразу.
          Лист подбора — отдельной кнопкой «Сформировать лист подбора» (режим скана и режим ленты не смешиваются).
          {pickListRefreshing ? ' Формируем лист подбора…' : ''}
        </p>
        {(data?.warehouses.length ?? 0) === 0 ? (
          <p className="assembly-warehouses__empty">Нажмите «Загрузить из WB»</p>
        ) : (
          <ul className="assembly-warehouses__list">
            {(data?.warehouses ?? []).map((wh) => (
              <li key={wh.id} className={wh.is_enabled ? '' : 'assembly-warehouses__item--off'}>
                <label className="assembly-warehouses__toggle" {...uiHint(
                  wh.is_enabled
                    ? 'Скрыть заказы этого склада из сборки (не влияет на статистику)'
                    : 'Показывать заказы этого склада в сборке и отдельной поставке',
                )}>
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

      {stage === 'complete' && (
        <section className="panel assembly-delivery-supplies">
          <h2 className="section-title">Поставки в доставке ({deliverySupplies.length})</h2>
          <p className="assembly-scan-hint">
            QR поставки нужен для приёмки на складе WB. Если при передаче в доставку окно печати
            закрылось без стикера — нажмите «Печать QR» для нужной поставки.
          </p>
          {deliverySupplies.length === 0 ? (
            <p className="assembly-warehouses__empty">Нет поставок, ожидающих сканирования на складе WB</p>
          ) : (
            <table className="assembly-table">
              <thead>
                <tr>
                  <th>ID поставки WB</th>
                  <th>Заказов</th>
                  <th>Создана</th>
                  <th>Действие</th>
                </tr>
              </thead>
              <tbody>
                {deliverySupplies.map((supply) => (
                  <tr key={supply.id}>
                    <td><code>{supply.wb_supply_id}</code></td>
                    <td>{supply.orders_count}</td>
                    <td>{new Date(supply.created_at).toLocaleString('ru-RU')}</td>
                    <td>
                      <button
                        type="button"
                        className="btn btn--small btn--primary"
                        onClick={() => void handlePrintSupplyBarcode(supply.id, supply.wb_supply_id)}
                        disabled={loading}
                      >
                        Печать QR
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )}

      <div className={`assembly-grid${stage === 'confirm' ? ' assembly-grid--scan' : ''}`}>
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
              {orders.length === 0 ? (
                <tr>
                  <td colSpan={10} className="assembly-table__empty">
                    {refreshing || syncing
                      ? 'Загрузка заказов…'
                      : stage === 'confirm'
                        ? 'Все заказы собраны — см. зелёный счётчик «Готовые»'
                        : 'Нет заказов на этой вкладке'}
                  </td>
                </tr>
              ) : orders.map((order) => {
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
                          <span
                            className="marking-badge marking-badge--error"
                            title={appendStickerHint(
                              order.marking_verify_error || 'ЧЗ отклонён',
                              order,
                            )}
                          >
                            ✕
                          </span>
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
                      {order.has_sticker ? formatStickerNumber(order) || '✓' : '—'}
                    </td>
                  <td className="assembly-table__actions">
                      {showAssemblyButton(order) && stage !== 'complete' && (
                      <button
                        type="button"
                        className="btn btn--small btn--primary"
                        onClick={() => handleSendToAssembly(order.id)}
                        disabled={loading}
                        {...uiHint('Перевести один заказ в статус «На сборке» в WB')}
                      >
                        На сборку
                      </button>
                    )}
                      {orderCanDeliver(order) && stage === 'confirm' && (
                      <span
                        {...hintWrapProps(
                          markingQueueBlocked
                            ? 'Сначала закройте ошибки ЧЗ'
                            : 'Добавить заказ в поставку WB',
                        )}
                      >
                        <button
                          type="button"
                          className="btn btn--small btn--secondary"
                          onClick={() => handleSendToDelivery(order)}
                          disabled={loading || markingQueueBlocked}
                        >
                          В доставку
                        </button>
                      </span>
                    )}
                      <button
                        type="button"
                        className="btn btn--small btn--ghost assembly-order-delete"
                        onClick={() => handleDeleteOrder(order)}
                        disabled={loading}
                        {...uiHint('Убрать заказ из текущей сборки в CRM (не отмена на WB)')}
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

        {stage !== 'confirm' && stage !== 'new' && (
        <div className="assembly-side">
          {stage === 'complete' && (
            <section className="panel assembly-scan-panel">
              <h2 className="section-title">Подсказка</h2>
              <p className="assembly-scan-hint">
                После сканирования QR поставки на складе WB заказы исчезнут из списка.
                Список обновляется при открытии вкладки и каждые 5 минут.
              </p>
            </section>
          )}
        </div>
        )}
      </div>

      {modal && (
        <AssemblyModal modal={modal} onClose={() => setModal(null)} loading={loading} />
      )}

      {markingListKind && (
        <AssemblyQueueListModal
          kind={markingListKind}
          orders={markingListOrders}
          loading={loading}
          onClose={() => setMarkingListKind(null)}
          onReplace={markingListKind === 'errors' ? (order) => void handleReplaceOrderFromList(order) : undefined}
          onReprint={
            markingListKind === 'ready'
              ? (order) => confirmReprintSticker(order, () => setMarkingListKind(null))
              : undefined
          }
          onDeliver={
            markingListKind === 'ready'
              ? (order) => {
                  if (!orderCanDeliver(order)) {
                    setError(orderBlockReason(order) || 'Заказ пока нельзя передать в доставку')
                    return
                  }
                  setMarkingListKind(null)
                  handleSendToDelivery(order)
                }
              : undefined
          }
        />
      )}

      <AssemblySyncOverlay visible={pickListRefreshing} marketplace="wb" />
    </>
  )
}

