import { Fragment, useCallback, useEffect, useLayoutEffect, useRef, useState, type ClipboardEvent, type FormEvent, type KeyboardEvent } from 'react'
import { flushSync } from 'react-dom'
import { Link, useParams } from 'react-router-dom'
import {
  bindMarking,
  deleteAssemblyOrder,
  restoreAssemblyOrder,
  deliverSupply,
  fetchAssemblySeller,
  fetchPickListArchive,
  fetchAssemblyStickers,
  type CancelledInSupplyNotice,
  fetchBatchRibbon,
  fetchMarkingStatus,
  fetchMoveSupplyTargets,
  moveOrdersToNewSupply,
  replaceOrderItem,
  resetAssemblyMarking,
  reprintOrderSticker,
  scanOrderBarcode,
  sendOrderToAssembly,
  sendOrderToDelivery,
  fetchSupplyBarcode,
  setAssemblyWorkflowMode,
  startAssembly,
  previewPickList,
  verifyMarking,
  type AssemblyOrder,
  type AssemblySupply,
  type AssemblySellerDetail,
  type AssemblyWorkflowMode,
  type PickList,
  type PrintOrder,
  type MarkingStatusResult,
  type VerifyMarkingResult,
  type SendToDeliveryResult,
  type DeliveryShippingParams,
  type MoveSupplyTarget,
} from '../api/assembly'
import { ApiError } from '../api/client'
import { syncOrders, fetchPickList } from '../api/orders'
import { syncSellerWarehouses, toggleSellerWarehouse } from '../api/sellers'
import {
  WORKFLOW_STEPS,
  buildDeliveryConfirmMessage,
  canSwitchToStage,
  orderBlockReason,
  orderCanDeliver,
  orderChzPending,
  orderNeedsChzVerify,
  orderStickerPrinted,
  assemblyDeliveryUnlocked,
  resolveWorkflowStep,
  assemblyScanErrorTitle,
  type ScanPhase,
  type StageKey,
} from '../utils/assemblyWorkflow'
import {
  buildChzVerifyReport,
  chzStatusLabel,
  MARKING_STATUS_POLL_MS,
  MARKING_VERIFY_POLL_MS,
  pickVerifyItemsForOrder,
  summarizeChzVerifyResult,
} from '../utils/markingVerify'
import { AssemblyModal, playAssemblyScanErrorBeep, type AssemblyModalState } from '../components/AssemblyModal'
import { DeliveryDestinationModal } from '../components/DeliveryDestinationModal'
import { BatchBindPanel } from '../components/BatchBindPanel'
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
  printSupplySticker,
  refreshPrintBridgeStatus,
  setPrintHolderMessage,
  warmFbsPrintWindow,
  preloadFbsSticker,
  type PrintChannel,
} from '../utils/printService'
import { isKioskPrintMode } from '../utils/printMode'
import { downloadPickListPdf } from '../utils/pickListPrint'
import { printBatchRibbon } from '../utils/batchRibbonPrint'
import { formatStickerNumber, appendStickerHint } from '../utils/stickerLabel'
import { applyMarkingScanKey, appendPastedMarking, quickMarkingCodeCheck } from '../utils/scanMarking'
import { useMarketplace } from '../context/MarketplaceContext'
import { useCrmNotice } from '../context/CrmNoticeContext'
import { uiHint, hintWrapProps } from '../utils/uiHint'
import {
  patchAssemblySellersCache,
  readAssemblySellerCache,
  writeAssemblySellerCache,
} from '../utils/assemblyCache'
import { OzonAssemblySellerPage } from './OzonAssemblySellerPage'
import './AssemblyPage.css'

const WB_COUNTS_POLL_MS = 120_000

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

function formatSupplyCreatedAt(iso: string): string {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleString('ru-RU', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return ''
  }
}

function sortAssemblyOrders(list: AssemblyOrder[]): AssemblyOrder[] {
  return [...list].sort((a, b) => {
    const rank = (order: AssemblyOrder) => {
      if (order.status === 'cancelled') return 0
      if (orderCanDeliver(order)) return 1
      if (orderStickerPrinted(order)) return 2
      return 3
    }
    const diff = rank(a) - rank(b)
    if (diff !== 0) return diff
    return b.wb_order_id - a.wb_order_id
  })
}

function assemblyOrderRowClass(order: AssemblyOrder): string | undefined {
  if (order.status === 'cancelled') return 'assembly-table__row--cancelled'
  if (orderCanDeliver(order)) return 'assembly-table__row--ready'
  return undefined
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
  const { marketplace } = useMarketplace()
  const { showSuccess, showError, flashPrintOk } = useCrmNotice()
  const noticeOk = (message: string, title = 'Готово') => showSuccess(title, message)
  const noticeFail = (title: string, err: unknown, fallback: string) => {
    showError(title, err instanceof Error ? err.message : fallback)
  }
  const id = Number(sellerId)
  const scanRef = useRef<HTMLInputElement>(null)
  const markingRef = useRef<HTMLInputElement>(null)
  const scanPanelRef = useRef<HTMLElement>(null)
  const markingBufferRef = useRef('')
  const scanPhaseRef = useRef<ScanPhase>('barcode')
  const markingLockRef = useRef(false)
  const scanBusyRef = useRef(false)
  const barcodeApiInFlightRef = useRef(false)
  const pendingOrderRef = useRef<PrintOrder | null>(null)
  const orderStickerCacheRef = useRef<Map<number, string>>(new Map())
  /** Автопечать стикера — строго один раз на заказ; повтор только через кнопку менеджера. */
  const autoPrintedOrderIdsRef = useRef<Set<number>>(new Set())
  const markingSubmitBusyRef = useRef(false)

  const [data, setData] = useState<AssemblySellerDetail | null>(
    () => readAssemblySellerCache(id, 'new'),
  )
  const [stage, setStage] = useState('new')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [scanValue, setScanValue] = useState('')
  const [markingValue, setMarkingValue] = useState('')
  const [scanPhase, setScanPhase] = useState<ScanPhase>('barcode')
  const [markingUiOpen, setMarkingUiOpen] = useState(false)
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
  const [verifyingChz, setVerifyingChz] = useState(false)
  const [verifyingChzOrderId, setVerifyingChzOrderId] = useState<number | null>(null)
  const [chzVerifyNotice, setChzVerifyNotice] = useState('')
  const verifyInFlightRef = useRef(false)
  const chzVerifyFailStreakRef = useRef(0)
  const [modal, setModal] = useState<AssemblyModalState | null>(null)
  const [movePicker, setMovePicker] = useState<{
    orderIds: number[]
    targets: MoveSupplyTarget[]
  } | null>(null)
  const [deliveryModal, setDeliveryModal] = useState<{
    title: string
    message: string
    wbSupplyId?: string
    printWin: Window | null
    onConfirm: (shipping: DeliveryShippingParams, printWin: Window | null) => void
  } | null>(null)
  const [pickListPreviews, setPickListPreviews] = useState<PickList[]>([])
  const [ribbonPrinting, setRibbonPrinting] = useState(false)
  const [pickListDownloading, setPickListDownloading] = useState(false)
  const [stickersFetching, setStickersFetching] = useState(false)
  const [stickerFetchingOrderId, setStickerFetchingOrderId] = useState<number | null>(null)
  const [buildVersion, setBuildVersion] = useState('')
  const [selectedMoveIds, setSelectedMoveIds] = useState<Set<number>>(new Set())
  const [pickListArchiveOpen, setPickListArchiveOpen] = useState(false)
  const [pickListArchive, setPickListArchive] = useState<PickList[]>([])
  const [pickListArchiveLoading, setPickListArchiveLoading] = useState(false)
  const cancelledNoticeShownRef = useRef(false)
  const stickerRefreshTimerRef = useRef<number | null>(null)
  const barcodeFocusTimerRef = useRef<number | null>(null)

  const warmStickerCacheFromOrders = useCallback((orderList: AssemblyOrder[]) => {
    for (const order of orderList) {
      const file = (order.sticker_file || '').trim()
      if (!file || !order.has_sticker) continue
      orderStickerCacheRef.current.set(order.id, file)
      preloadFbsSticker(file)
    }
  }, [])

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
      if (pickStage === 'confirm' && fresh.orders?.length) {
        warmStickerCacheFromOrders(fresh.orders)
        const stillMissingStickers = fresh.orders.some(
          (order) => (order.wb_supplier_status || '').trim() === 'confirm' && !order.has_sticker,
        )
        if (!stillMissingStickers && stickerRefreshTimerRef.current) {
          window.clearInterval(stickerRefreshTimerRef.current)
          stickerRefreshTimerRef.current = null
        }
      }
      if (pickStage === 'new' || pickStage === 'confirm') {
        if (fresh.active_pick_lists?.length) {
          setPickListPreviews(fresh.active_pick_lists)
        } else if (fresh.active_pick_list?.items?.length) {
          setPickListPreviews([fresh.active_pick_list])
        }
      }
    } catch (err) {
      if (!silent) {
        const msg = err instanceof Error ? err.message : 'Ошибка загрузки'
        setError(msg)
        showError('Загрузка сборки', msg)
      }
    } finally {
      if (silent) {
        setRefreshing(false)
      }
    }
  }, [id, stage, showError, warmStickerCacheFromOrders])

  const refreshAssemblyStickersInBackground = useCallback(() => {
    if (!id) return
    if (stickerRefreshTimerRef.current) {
      window.clearInterval(stickerRefreshTimerRef.current)
    }
    void fetchAssemblyStickers(id).catch(() => {})
    let ticks = 0
    stickerRefreshTimerRef.current = window.setInterval(() => {
      ticks += 1
      void load({ silent: true, stageKey: 'confirm' })
      if (ticks >= 80) {
        if (stickerRefreshTimerRef.current) {
          window.clearInterval(stickerRefreshTimerRef.current)
          stickerRefreshTimerRef.current = null
        }
      }
    }, 1500)
  }, [id, load])

  const notifyCancelledInSupplies = useCallback((items: CancelledInSupplyNotice[]) => {
    if (!items.length) return
    const sample = items[0]
    const more = items.length > 1 ? ` и ещё ${items.length - 1}` : ''
    showError(
      'Отмена в поставке',
      `Покупатель отменил заказ WB #${sample.wb_order_id} в поставке ${sample.wb_supply_id}${more}. `
        + 'Строка подсветится красным — удалите из CRM вручную.',
    )
  }, [showError])

  const applySavedPickList = useCallback((fresh: AssemblySellerDetail | null) => {
    if (fresh?.active_pick_lists?.length) {
      setPickListPreviews(fresh.active_pick_lists)
      return
    }
    if (fresh?.active_pick_list?.items?.length) {
      setPickListPreviews([fresh.active_pick_list])
      return
    }
    setPickListPreviews([])
  }, [])

  useEffect(() => {
    if (isKioskPrintMode()) {
      setBridgeOk(false)
      return
    }
    refreshPrintBridgeStatus()
      .then((health) => {
        setBridgeOk(health.ok)
        setBridgePrinter(health.printer || '')
      })
      .catch(() => setBridgeOk(false))
  }, [])

  useEffect(() => {
    fetch('/api/health/')
      .then((res) => (res.ok ? res.json() : null))
      .then((payload: { build?: string } | null) => {
        if (payload?.build) setBuildVersion(payload.build)
      })
      .catch(() => {})
  }, [])

  useEffect(
    () => () => {
      if (stickerRefreshTimerRef.current) {
        window.clearInterval(stickerRefreshTimerRef.current)
      }
      if (barcodeFocusTimerRef.current) {
        window.clearInterval(barcodeFocusTimerRef.current)
      }
    },
    [],
  )

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
        if (stage === 'confirm' && fresh.orders?.length) {
          warmStickerCacheFromOrders(fresh.orders)
        }
        applySavedPickList(fresh)
      } catch (err) {
        if (!cancelled && !cached) {
          setError(err instanceof Error ? err.message : 'Ошибка загрузки')
          showError('Загрузка сборки', err instanceof Error ? err.message : 'Ошибка загрузки')
        }
      } finally {
        if (!cancelled) setRefreshing(false)
      }
    })()

    return () => {
      cancelled = true
    }
  }, [id, stage, applySavedPickList, warmStickerCacheFromOrders])

  useEffect(() => {
    if (!id || stage !== 'confirm') return
    const missing = (data?.orders ?? []).some(
      (order) => (order.wb_supplier_status || '').trim() === 'confirm' && !order.has_sticker,
    )
    if (missing && !stickerRefreshTimerRef.current) {
      void refreshAssemblyStickersInBackground()
    }
  }, [id, stage, data?.orders, refreshAssemblyStickersInBackground])

  useEffect(() => {
    if (!id) return
    const tick = () => {
      if (document.visibilityState !== 'visible') return
      void load({ silent: true })
    }
    const timer = window.setInterval(tick, WB_COUNTS_POLL_MS)
    const onVisible = () => {
      if (document.visibilityState === 'visible') void load({ silent: true })
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [id, load])

  useEffect(() => {
    cancelledNoticeShownRef.current = false
  }, [id])

  useEffect(() => {
    if (stage !== 'confirm' || !data?.cancelled_in_supplies?.length) return
    if (cancelledNoticeShownRef.current) return
    cancelledNoticeShownRef.current = true
    notifyCancelledInSupplies(data.cancelled_in_supplies)
  }, [data?.cancelled_in_supplies, stage, notifyCancelledInSupplies])

  const refreshMarkingStatus = useCallback(async () => {
    if (!id) return
    try {
      setMarkingStatus(await fetchMarkingStatus(id))
    } catch {
      // Фоновое обновление панелей ЧЗ — без алертов
    }
  }, [id])

  const runMarkingVerify = useCallback(async (opts?: {
    silent?: boolean
    forceRecheck?: boolean
    orderIds?: number[]
  }) => {
    if (!id) return null
    const silent = opts?.silent ?? true
    if (verifyInFlightRef.current) {
      if (silent) return null
      const started = Date.now()
      while (verifyInFlightRef.current && Date.now() - started < 20000) {
        await new Promise((resolve) => window.setTimeout(resolve, 200))
      }
    }
    verifyInFlightRef.current = true
    try {
      const result = await verifyMarking(id, opts?.orderIds, {
        forceRecheck: opts?.forceRecheck ?? !silent,
      })
      await refreshMarkingStatus()
      chzVerifyFailStreakRef.current = 0
      if (silent) {
        setChzVerifyNotice('')
      }
      return result
    } catch (err) {
      if (!silent) throw err
      chzVerifyFailStreakRef.current += 1
      if (chzVerifyFailStreakRef.current >= 3) {
        setChzVerifyNotice(
          err instanceof Error
            ? `${err.message} CRM продолжит опрос каждые 4 секунды. Нажмите «Проверить ЧЗ» для ответа по каждому заказу.`
            : 'WB не ответил по ЧЗ. CRM продолжит опрос каждые 4 секунды.',
        )
      }
      return null
    } finally {
      verifyInFlightRef.current = false
    }
  }, [id, refreshMarkingStatus])

  useLayoutEffect(() => {
    if (stage !== 'confirm') return
    if (markingUiOpen) {
      focusMarkingInput()
    } else if (!scanBusy) {
      focusBarcodeInput()
    }
  }, [markingUiOpen, scanBusy, stage])

  useEffect(() => {
    pendingOrderRef.current = pendingOrder
  }, [pendingOrder])

  useEffect(() => {
    if (scanPhase !== 'marking') return
    markingBufferRef.current = ''
    setMarkingValue('')
  }, [scanPhase])

  useEffect(() => {
    if (stage !== 'confirm') return
    warmFbsPrintWindow()
  }, [stage])

  useEffect(() => {
    if (stage !== 'confirm') return
    const onWindowFocus = () => {
      if (markingUiOpen || scanBusyRef.current) return
      focusBarcodeInput()
    }
    window.addEventListener('focus', onWindowFocus)
    return () => window.removeEventListener('focus', onWindowFocus)
  }, [stage, markingUiOpen])

  useEffect(() => {
    if (!id || stage !== 'confirm') return

    const tick = () => {
      if (document.visibilityState !== 'visible') return
      void refreshMarkingStatus()
    }
    tick()
    const statusTimer = window.setInterval(tick, MARKING_STATUS_POLL_MS)
    const onVis = () => {
      if (document.visibilityState === 'visible') void refreshMarkingStatus()
    }
    document.addEventListener('visibilitychange', onVis)

    return () => {
      window.clearInterval(statusTimer)
      document.removeEventListener('visibilitychange', onVis)
    }
  }, [id, stage, refreshMarkingStatus])

  useEffect(() => {
    if (!id || stage !== 'confirm') return
    const tick = () => {
      if (document.visibilityState !== 'visible') return
      void runMarkingVerify({ silent: true, forceRecheck: false })
    }
    tick()
    const verifyTimer = window.setInterval(tick, MARKING_VERIFY_POLL_MS)
    return () => window.clearInterval(verifyTimer)
  }, [id, stage, runMarkingVerify])

  useEffect(() => {
    if (!id || stage !== 'complete') return

    const refreshDelivery = async () => {
      if (document.visibilityState !== 'visible') return
      if (!syncInFlightRef.current) {
        syncInFlightRef.current = true
        try {
          await syncOrders(id, 'delivery', { background: false })
        } catch {
          // фоновая синхронизация scanDt — без алертов
        } finally {
          syncInFlightRef.current = false
        }
      }
      await load({ silent: true })
    }

    void refreshDelivery()
    const interval = window.setInterval(() => void refreshDelivery(), 5 * 60 * 1000)
    const onVis = () => {
      if (document.visibilityState === 'visible') void refreshDelivery()
    }
    document.addEventListener('visibilitychange', onVis)
    return () => {
      window.clearInterval(interval)
      document.removeEventListener('visibilitychange', onVis)
    }
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

  function cacheOrderSticker(order: Pick<PrintOrder, 'id' | 'sticker_file'>) {
    const file = (order.sticker_file || '').trim()
    if (file) {
      orderStickerCacheRef.current.set(order.id, file)
    }
  }

  function shouldOpenMarkingForOrder(orderId: number): boolean {
    if (autoPrintedOrderIdsRef.current.has(orderId)) return false
    return true
  }

  function releaseBarcodeForNextScan(focusDurationMs = 15000) {
    scanBusyRef.current = false
    setScanBusy(false)
    keepBarcodeFocus(focusDurationMs)
    focusBarcodeInput()
  }

  function openMarkingScan(order: PrintOrder, _message?: string) {
    if (!shouldOpenMarkingForOrder(order.id)) return
    const alreadyOpen = markingLockRef.current && scanPhaseRef.current === 'marking'
    markingLockRef.current = true
    scanPhaseRef.current = 'marking'
    flushSync(() => {
      setMarkingUiOpen(true)
      setScanPhase('marking')
      setPendingOrder(order)
      setScanValue('')
      if (!alreadyOpen) {
        markingBufferRef.current = ''
        setMarkingValue('')
      }
    })
    pendingOrderRef.current = order
    cacheOrderSticker(order)
    const sticker = (order.sticker_file || '').trim()
    if (sticker) preloadFbsSticker(sticker)
    focusMarkingInput()
  }

  function focusMarkingInput() {
    scanPanelRef.current?.scrollIntoView({ block: 'nearest' })
    markingRef.current?.focus()
  }

  function focusBarcodeInput() {
    scanPanelRef.current?.scrollIntoView({ block: 'nearest' })
    scanRef.current?.focus()
    scanRef.current?.select()
  }

  function keepBarcodeFocus(durationMs = 15000) {
    if (barcodeFocusTimerRef.current) {
      window.clearInterval(barcodeFocusTimerRef.current)
    }
    focusBarcodeInput()
    const started = Date.now()
    barcodeFocusTimerRef.current = window.setInterval(() => {
      if (Date.now() - started > durationMs) {
        if (barcodeFocusTimerRef.current) {
          window.clearInterval(barcodeFocusTimerRef.current)
          barcodeFocusTimerRef.current = null
        }
        return
      }
      if (markingLockRef.current || scanPhaseRef.current === 'marking') return
      focusBarcodeInput()
    }, 80)
  }

  function findLocalOrderByBarcode(
    barcode: string,
    orderList: AssemblyOrder[],
  ): AssemblyOrder | undefined {
    const code = normalizeScanCode(barcode)
    return orderList.find((order) => {
      if (normalizeScanCode(order.barcode) !== code) return false
      if (orderStickerPrinted(order) && order.marking_verify_status !== 'error') return false
      const wb = (order.wb_supplier_status || '').trim()
      return (
        order.status === 'in_picking' ||
        order.status === 'assembled' ||
        (wb === 'confirm' && order.status === 'new')
      )
    })
  }

  function findLocalMarkingOrder(barcode: string, orderList: AssemblyOrder[]): AssemblyOrder | undefined {
    const order = findLocalOrderByBarcode(barcode, orderList)
    if (!order || !order.requires_marking || !orderNeedsMarkingScan(order)) return undefined
    if (
      !order.has_sticker &&
      !Boolean((order.sticker_file || '').trim() || orderStickerCacheRef.current.get(order.id))
    ) {
      return undefined
    }
    return order
  }

  function findLocalReadyPrintOrder(barcode: string, orderList: AssemblyOrder[]): AssemblyOrder | undefined {
    const order = findLocalOrderByBarcode(barcode, orderList)
    if (!order || order.requires_marking || !canAutoPrintOrder(order)) return undefined
    if (!stickerPayloadForOrder(order)) return undefined
    return order
  }

  function stickerPayloadForOrder(order: Pick<AssemblyOrder, 'id' | 'sticker_file'>): string {
    return (order.sticker_file || '').trim() || orderStickerCacheRef.current.get(order.id) || ''
  }

  function canAutoPrintOrder(order: Pick<AssemblyOrder, 'id' | 'status'>): boolean {
    if (autoPrintedOrderIdsRef.current.has(order.id)) return false
    return !orderStickerPrinted(order as AssemblyOrder)
  }

  function markAutoPrinted(orderId: number): void {
    autoPrintedOrderIdsRef.current.add(orderId)
  }

  function showScanError(
    message: string,
    title: string,
    onDismiss?: () => void,
  ) {
    playAssemblyScanErrorBeep()
    setModal({
      kind: 'scan-error',
      title,
      message,
      onDismiss: onDismiss ?? (() => focusMarkingInput()),
    })
  }

  function resetScanFlow(force = false) {
    if (markingLockRef.current && !force) {
      focusMarkingInput()
      return
    }
    markingLockRef.current = false
    scanPhaseRef.current = 'barcode'
    markingBufferRef.current = ''
    flushSync(() => {
      setMarkingUiOpen(false)
      setScanPhase('barcode')
      setPendingOrder(null)
      setMarkingValue('')
      setScanValue('')
    })
    pendingOrderRef.current = null
    focusBarcodeInput()
  }

  async function printSticker(
    base64: string,
    preopened?: Window | null,
    onPrintScheduled?: () => void,
  ) {
    const payload = (base64 || '').trim()
    if (!payload) {
      setPrintHolderMessage(preopened ?? null, 'Стикер пустой — нечего печатать')
      throw new Error('Стикер пустой — нечего печатать')
    }
    const channel = await printFbsSticker(payload, true, preopened, onPrintScheduled)
    if (channel === 'bridge') {
      setBridgeOk(true)
    }
    return channel
  }

  async function finishPrint(order: PrintOrder, preopened?: Window | null): Promise<boolean> {
    if (!canAutoPrintOrder(order)) {
      closePrintHolder(preopened)
      return false
    }
    const file = (order.sticker_file || '').trim()
    if (!file) {
      closePrintHolder(preopened)
      throw new Error(
        `WB не вернул стикер для заказа #${order.wb_order_id}. Обновите заказы или обратитесь к администратору.`,
      )
    }
    markAutoPrinted(order.id)
    setStickerPreview(file)
    setLastPrinted(order as unknown as AssemblyOrder)
    cacheOrderSticker(order)
    preloadFbsSticker(file)
    void printSticker(file, preopened, () => releaseBarcodeForNextScan())
      .then(() => {
        flashPrintOk()
        releaseBarcodeForNextScan()
      })
      .catch(() => {})
    resetScanFlow(true)
    releaseBarcodeForNextScan()
    setStage('confirm')
    void refreshMarkingStatus()
    return true
  }

  function confirmReprintSticker(order: AssemblyOrder, onDone?: () => void) {
    setModal({
      kind: 'confirm',
      title: 'Повторная печать стикера',
      message:
        `Стикер заказа WB #${order.wb_order_id} уже был напечатан.\n\n` +
        'Печатать повторно только если стикер повреждён или потерян.\n' +
        'Остаток в CRM не списывается. Продолжить?',
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
      const file = (result.order.sticker_file || '').trim()
      if (file) {
        setStickerPreview(file)
      }
      await printSticker(result.order.sticker_file, printWin)
      flashPrintOk()
      onDone?.()
    } catch (err) {
      closePrintHolder(printWin)
      noticeFail('Печать стикера', err, 'Не удалось распечатать стикер')
    } finally {
      setLoading(false)
    }
  }

  function handleTransferToAssembly() {
    const count = data?.assembly_ready ?? data?.assembly_eligible ?? 0
    if (!id || count < 1) return
    const pending = data?.assembly_pending ?? 0
    setModal({
      kind: 'confirm',
      title: 'Передать на сборку',
      message:
        `Передать на сборку ${count} заказов в Wildberries?\n\n` +
        (pending > 0
          ? `Ещё ${pending} зак. ждут фоновой загрузки из WB — они не войдут в эту передачу.\n\n`
          : '') +
        'CRM создаст поставки по складам, сформирует листы подбора. ' +
        'Стикеры подтянутся в фоне сразу после передачи.',
      confirmLabel: 'Передать',
      onConfirm: () => void runTransferToAssembly(),
    })
  }

  async function runTransferToAssembly() {
    if (!id) return
    setError('')
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
      if (result.stickers_deferred) {
        msg += '. Стикеры подтягиваются в фоне'
      } else if (result.sticker_errors) {
        msg += `. Ошибка стикеров: ${result.sticker_errors}`
      }
      const lists = result.active_pick_lists?.length
        ? result.active_pick_lists
        : result.pick_lists?.length
          ? result.pick_lists
          : result.pick_list
            ? [result.pick_list]
            : []
      if (lists.length) {
        setPickListPreviews(lists)
        if (result.pick_lists_count) {
          msg += `, листов подбора: ${result.pick_lists_count}`
        }
      }
      noticeOk(msg, 'На сборке')
      if (result.sync_stale_message) {
        showSuccess('Синхронизация WB', result.sync_stale_message)
      }
      if (result.sticker_errors && !result.stickers_deferred) {
        showError('Стикеры не подтянулись', result.sticker_errors)
      }
      if (result.pick_list_error) {
        showError('Лист подбора', result.pick_list_error)
      }
      if (id && result.counts) {
        patchAssemblySellersCache(marketplace, Number(id), {
          new: result.counts.new ?? 0,
          in_picking: result.counts.in_picking ?? 0,
          in_delivery: result.counts.in_delivery ?? 0,
          total_active:
            (result.counts.new ?? 0)
            + (result.counts.in_picking ?? 0)
            + (result.counts.in_delivery ?? 0),
        })
      }
      setStage('confirm')
      await load({ stageKey: 'confirm' })
      if (result.stickers_deferred) {
        void refreshAssemblyStickersInBackground()
      }
    } catch (err) {
      noticeFail('Передача на сборку', err, 'Ошибка передачи на сборку')
    } finally {
      setLoading(false)
    }
  }

  function handleDeleteOrder(order: AssemblyOrder) {
    const cancelled = isOrderCancelled(order)
    setModal({
      kind: 'confirm',
      title: cancelled ? 'Удалить отменённый заказ из CRM' : 'Удалить заказ',
      message: cancelled
        ? `Заказ WB #${order.wb_order_id} отменён покупателем.\n\n` +
          `Баркод: ${order.barcode}\n` +
          'Удалите его из CRM, чтобы убрать из поставки и передать в доставку остальные заказы.'
        : `Удалить заказ WB #${order.wb_order_id} из сборки?\n\n` +
          `Баркод: ${order.barcode}\n` +
          'Заказ скроется из таблицы, но в поставке WB может остаться и блокировать доставку. ' +
          'Восстановить можно в блоке «Удалённые из сборки».',
      confirmLabel: cancelled ? 'Удалить из CRM' : 'Удалить',
      onConfirm: () => void runDeleteOrder(order.id),
    })
  }

  function handleRestoreOrder(order: AssemblyOrder) {
    setModal({
      kind: 'confirm',
      title: 'Восстановить заказ',
      message:
        `Вернуть заказ WB #${order.wb_order_id} в сборку?\n\n` +
        `Баркод: ${order.barcode}\n` +
        'Заказ снова появится в таблице. Если он на сборке в WB — CRM подтянет стикер и добавит в лист подбора.',
      confirmLabel: 'Восстановить',
      onConfirm: () => void runRestoreOrder(order.id),
    })
  }

  async function runRestoreOrder(orderId: number) {
    if (!id) return
    setModal(null)
    setError('')
    setLoading(true)
    try {
      const result = await restoreAssemblyOrder(id, orderId)
      noticeOk(result.message, 'Восстановление')
      await load({ stageKey: 'confirm', silent: false })
      void refreshMarkingStatus()
    } catch (err) {
      noticeFail('Восстановление', err, 'Не удалось восстановить заказ')
    } finally {
      setLoading(false)
    }
  }

  async function runDeleteOrder(orderId: number) {
    if (!id) return
    setError('')
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
      noticeOk(`Заказ WB #${result.order.wb_order_id} удалён из сборки`)
      await load({ silent: true })
    } catch (err) {
      noticeFail('Удаление заказа', err, 'Не удалось удалить заказ')
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
      noticeOk(mode === 'batch' ? 'Режим: лента стикеров' : 'Режим: пошаговый скан', 'Режим сборки')
      resetScanFlow(true)
    } catch (err) {
      noticeFail('Режим сборки', err, 'Не удалось сменить режим сборки')
    }
  }

  async function handlePrintBatchRibbon() {
    if (!id) return
    setError('')
    setRibbonPrinting(true)
    const printWin = openPrintHolder()
    try {
      const result = await fetchBatchRibbon(id)
      if (!result.items?.length) {
        closePrintHolder(printWin)
        showError('Лента стикеров', 'В ленте нет стикеров. Сначала сформируйте лист подбора по выбранному складу.')
        return
      }
      const printed = await printBatchRibbon(result.items, true, printWin)
      if (!printed) {
        closePrintHolder(printWin)
        showError('Печать ленты', 'Не удалось открыть печать — разрешите всплывающие окна или установите агент печати')
        return
      }
      noticeOk(
        `Лента отправлена на печать: ${result.stickers_count} стикеров в ${result.groups_count} группах`,
        'Лента стикеров',
      )
    } catch (err) {
      closePrintHolder(printWin)
      noticeFail('Лента стикеров', err, 'Не удалось подготовить ленту стикеров')
    } finally {
      setRibbonPrinting(false)
    }
  }

  async function handleFetchOrderSticker(order: AssemblyOrder) {
    if (!id) return
    setStickerFetchingOrderId(order.id)
    try {
      const result = await fetchAssemblyStickers(id, [order.id], true)
      await load({ silent: false, stageKey: stage })
      if (result.fetched > 0 && result.still_missing === 0) {
        showSuccess(
          'Стикер загружен',
          result.message || `Стикер для #${order.wb_order_id} подтянут из WB. Можно сканировать.`,
        )
      } else if (result.fetched > 0) {
        showError(
          'Стикер не полный',
          result.message || `WB вернул данные, но файл стикера для #${order.wb_order_id} пуст.`,
        )
      } else {
        showError(
          'Стикер не получен',
          result.message || `WB не вернул стикер для #${order.wb_order_id}. Проверьте, что заказ на сборке в ЛК WB.`,
        )
      }
    } catch (err) {
      showError(
        'Ошибка стикера',
        err instanceof Error ? err.message : `Не удалось подтянуть стикер для #${order.wb_order_id}`,
      )
    } finally {
      setStickerFetchingOrderId(null)
    }
  }

  async function handleFetchMissingStickers() {
    if (!id) return
    setStickersFetching(true)
    try {
      const result = await fetchAssemblyStickers(id)
      await load({ silent: false, stageKey: 'confirm' })
      if (result.still_missing > 0) {
        showError(
          'Не все стикеры загружены',
          result.message || `Загружено ${result.fetched} из ${result.requested}. Проверьте заказы в ЛК WB.`,
        )
      } else {
        showSuccess(
          'Стикеры загружены',
          result.message || `Загружено ${result.fetched} из ${result.requested}. Можно сканировать.`,
        )
      }
    } catch (err) {
      if (err instanceof ApiError && err.code === 'no_missing_stickers') {
        showSuccess('Стикеры уже в CRM', err.message)
        await load({ silent: false, stageKey: 'confirm' })
        return
      }
      showError('Ошибка стикеров', err instanceof Error ? err.message : 'Не удалось загрузить стикеры из WB')
    } finally {
      setStickersFetching(false)
    }
  }

  async function resolvePickListsForDownload(target?: PickList): Promise<PickList[]> {
    if (target?.items?.length) return [target]

    const saved = pickListPreviews.some((list) => list.items?.length)
      ? pickListPreviews
      : data?.active_pick_lists?.some((list) => list.items?.length)
        ? data.active_pick_lists
        : data?.active_pick_list?.items?.length
          ? [data.active_pick_list]
          : []

    const withItems = saved.filter((list) => list.items?.length)
    if (withItems.length) return withItems

    if (!id) return []

    const preview = await previewPickList(id, 'confirm')
    const fromApi = preview.pick_lists?.length
      ? preview.pick_lists
      : preview.pick_list?.pick_lists?.length
        ? preview.pick_list.pick_lists
        : preview.pick_list?.items?.length
          ? [preview.pick_list]
          : []
    return fromApi.filter((list) => list.items?.length)
  }

  async function handleDownloadPickListPdf(target?: PickList) {
    if (!id) return
    setError('')
    setPickListDownloading(true)
    try {
      const lists = await resolvePickListsForDownload(target)
      if (!lists.length) {
        showError(
          'Лист подбора',
          'Нет заказов на сборке для листа подбора. Обновите заказы из WB.',
        )
        return
      }
      for (const pickList of lists) {
        if (!downloadPickListPdf(pickList)) {
          showError('PDF листа подбора', 'Не удалось открыть PDF — разрешите всплывающие окна в браузере')
          return
        }
      }
      if (!pickListPreviews.length && lists.length) {
        setPickListPreviews(lists)
      }
    } catch (err) {
      noticeFail('PDF листа подбора', err, 'Не удалось сформировать PDF листа подбора')
    } finally {
      setPickListDownloading(false)
    }
  }

  async function handleSyncWarehouses() {
    if (!id) return
    setRefreshing(true)
    setError('')
    try {
      const result = await syncSellerWarehouses(id)
      noticeOk(`Склады WB обновлены: ${result.total} шт. После выбора склада нажмите «Сформировать лист подбора».`, 'Склады WB')
      await load({ silent: true })
    } catch (err) {
      noticeFail('Склады WB', err, 'Ошибка загрузки складов WB')
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
      noticeOk(
        isEnabled
          ? 'Склад включён. Нажмите «Сформировать лист подбора».'
          : 'Склад выключен. Нажмите «Сформировать лист подбора», если нужен новый список.',
        'Склад FBS',
      )
    } catch (err) {
      setData((current) => (
        current ? { ...current, warehouses: previousWarehouses } : current
      ))
      noticeFail('Склад FBS', err, 'Ошибка переключения склада')
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
    setLoading(true)
    try {
      const result = await sendOrderToAssembly(id, orderId)
      let msg = `Шаг 1: заказ WB #${result.order.wb_order_id} на сборке в WB`
      if (result.stickers_deferred) msg += ', стикер подтягивается в фоне'
      else if (result.stickers_fetched) msg += ', стикер загружен'
      if (result.sticker_error) msg += `. Ошибка стикера: ${result.sticker_error}`
      noticeOk(msg, 'На сборке')
      setStage('confirm')
      await load({ stageKey: 'confirm' })
      if (result.stickers_deferred) {
        void refreshAssemblyStickersInBackground()
      }
    } catch (err) {
      noticeFail('Отправка на сборку', err, 'Ошибка отправки на сборку')
    } finally {
      setLoading(false)
    }
  }

  async function handleSync() {
    if (!id) return
    setError('')
    syncInFlightRef.current = true
    setSyncing(true)
    try {
      const result = await syncOrders(id, 'quick')
      await load({ silent: true })
      if (result.cancelled_in_supplies?.length) {
        notifyCancelledInSupplies(result.cancelled_in_supplies)
      } else {
        noticeOk('Заказы обновлены', 'Синхронизация WB')
      }
    } catch (err) {
      noticeFail('Синхронизация WB', err, 'Ошибка синхронизации с WB')
    } finally {
      syncInFlightRef.current = false
      setSyncing(false)
    }
  }

  async function handleOpenPickListArchive() {
    if (!id) return
    setPickListArchiveLoading(true)
    try {
      const result = await fetchPickListArchive(id)
      setPickListArchive(result.pick_lists)
      setPickListArchiveOpen(true)
    } catch (err) {
      noticeFail('Архив листов', err, 'Не удалось загрузить архив листов подбора')
    } finally {
      setPickListArchiveLoading(false)
    }
  }

  async function handleDownloadArchivePickList(pickListId: number) {
    setPickListArchiveLoading(true)
    try {
      const pickList = await fetchPickList(pickListId)
      if (!downloadPickListPdf(pickList)) {
        showError('PDF листа подбора', 'Не удалось открыть PDF — разрешите всплывающие окна в браузере')
      }
    } catch (err) {
      noticeFail('PDF листа подбора', err, 'Не удалось скачать лист подбора')
    } finally {
      setPickListArchiveLoading(false)
    }
  }

  function openDeliveryModal(
    title: string,
    message: string,
    onRun: (shipping: DeliveryShippingParams, printWin: Window | null) => void,
    wbSupplyId?: string,
  ) {
    const printWin = openPrintHolder()
    if (!printWin) {
      showError(
        'Печать',
        'Не удалось открыть окно печати. Разрешите всплывающие окна для CRM в настройках Chrome.',
      )
      return
    }
    setPrintHolderMessage(printWin, 'Выберите пункт отгрузки…')
    setDeliveryModal({
      title,
      message,
      wbSupplyId,
      printWin,
      onConfirm: (shipping) => {
        setDeliveryModal(null)
        setPrintHolderMessage(printWin, 'Передача в доставку WB…')
        onRun(shipping, printWin)
      },
    })
  }

  function findOrderWbSupplyId(order: AssemblyOrder): string | undefined {
    const supplies = [
      ...(data?.active_supplies ?? []),
      ...(data?.delivery_supplies ?? []),
    ]
    for (const supply of supplies) {
      if ((supply.orders ?? []).some((item) => item.id === order.id)) {
        return supply.wb_supply_id
      }
    }
    return undefined
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
    openDeliveryModal(
      'Передача в доставку WB',
      buildDeliveryConfirmMessage(order),
      (shipping, printWin) => void runSendToDelivery(order, shipping, printWin),
      findOrderWbSupplyId(order),
    )
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
      setPrintHolderMessage(printWin, error || 'WB не вернул ШК поставки')
      return { error }
    }
    try {
      const channel = await printSupplySticker(file, true, printWin)
      if (channel === 'bridge') {
        setBridgeOk(true)
      }
      return { channel }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Не удалось отправить QR поставки на печать'
      setPrintHolderMessage(printWin, msg)
      return { error: msg }
    }
  }

  async function handlePrintSupplyBarcode(supplyId: number, wbSupplyId: string) {
    if (!id) return
    setError('')
    const printWin = openPrintHolder()
    if (!printWin) {
      showError(
        'Печать',
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
        setPrintHolderMessage(printWin, 'WB не вернул изображение QR поставки')
        throw new Error('WB не вернул изображение QR поставки')
      }
      const channel = await printSupplySticker(file, true, printWin)
      if (channel === 'bridge') {
        setBridgeOk(true)
      }
      const via = channel === 'bridge' ? 'Xprinter' : 'Chrome'
      noticeOk(`QR поставки ${wbSupplyId || result.wb_supply_id} → ${via}`, 'QR поставки')
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Не удалось распечатать QR поставки'
      if (printWin && !printWin.closed) {
        setPrintHolderMessage(printWin, msg)
      }
      showError('QR поставки', msg)
    } finally {
      setLoading(false)
    }
  }

  async function runSendToDelivery(
    order: AssemblyOrder,
    shipping: DeliveryShippingParams,
    printWin: Window | null,
  ) {
    if (!id) return
    setError('')
    setLoading(true)
    try {
      const result = await sendOrderToDelivery(id, order.id, shipping)
      const scLabel = result.shipping_point_id
        ? `, СЦ #${result.shipping_point_id}`
        : `, СЦ #${shipping.shipping_point_id}`
      const msg = `Шаг 4: заказ WB #${result.order.wb_order_id} передан в доставку${scLabel}`
      setLastPrinted(null)
      setStickerPreview(null)
      setStage('complete')
      await load({ stageKey: 'complete', silent: false })
      void refreshMarkingStatus()

      const printResult = await printSupplyBarcodeAfterDelivery(result, printWin)
      if (printResult.channel) {
        const via = printResult.channel === 'bridge' ? ', QR → Xprinter' : ', QR → Chrome'
        noticeOk(msg + via, 'В доставку')
        closePrintHolder(printWin)
      } else if (printResult.error) {
        closePrintHolder(printWin)
        showError('QR поставки', `Заказ передан в доставку. QR поставки не напечатан: ${printResult.error}`)
      } else {
        closePrintHolder(printWin)
        noticeOk(msg, 'В доставку')
      }
    } catch (err) {
      closePrintHolder(printWin)
      noticeFail('Доставка', err, 'Ошибка отправки в доставку')
    } finally {
      setLoading(false)
    }
  }

  function showChzVerifyModal(result: VerifyMarkingResult) {
    const summary = summarizeChzVerifyResult(result)
    setModal({
      kind: 'block',
      title: summary.title,
      message: buildChzVerifyReport(result),
    })
    if (summary.tone === 'error') {
      setMarkingListKind('errors')
    }
  }

  async function handleForceVerifyChz(orderIds?: number[]) {
    if (!id) return
    if (orderIds?.length === 1) {
      setVerifyingChzOrderId(orderIds[0])
    } else {
      setVerifyingChz(true)
    }
    try {
      const result = await runMarkingVerify({
        silent: false,
        forceRecheck: true,
        orderIds,
      })
      await load({ silent: true })
      if (!result) {
        showError('Проверка ЧЗ', 'Не удалось спросить WB. Нажмите «Проверить ЧЗ» ещё раз.')
        return
      }
      if (!result.results.length) {
        showError(
          'Проверка ЧЗ',
          'WB нечего проверять: у готовых заказов нет кода ЧЗ или проверка уже завершена. Обновите заказы и повторите.',
        )
        return
      }
      showChzVerifyModal(result)
    } catch (err) {
      noticeFail('Проверка ЧЗ', err, 'Не удалось проверить Честный знак в WB')
    } finally {
      setVerifyingChz(false)
      setVerifyingChzOrderId(null)
    }
  }

  async function handleVerifyOrderChz(order: AssemblyOrder) {
    if (!id) return
    setVerifyingChzOrderId(order.id)
    try {
      const result = await runMarkingVerify({
        silent: false,
        forceRecheck: true,
        orderIds: [order.id],
      })
      await refreshMarkingStatus()
      await load({ silent: true })
      if (!result) {
        showError('Проверка ЧЗ', `Не удалось спросить WB по заказу #${order.wb_order_id}.`)
        return
      }
      const item = pickVerifyItemsForOrder(result, order.id)
      if (!item) {
        showError(
          'Проверка ЧЗ',
          `WB не вернул статус по заказу #${order.wb_order_id}. Повторите через несколько секунд.`,
        )
        return
      }
      setModal({
        kind: 'block',
        title: `WB #${order.wb_order_id}: ${chzStatusLabel(item.status)}`,
        message:
          item.status === 'error' && item.error
            ? `${item.error}\n\nЕсли сканер передал код не полностью — нажмите «Сброс ЧЗ» и отсканируйте DataMatrix заново.`
            : item.status === 'pending'
              ? 'WB ещё не дал финальный ответ. CRM спросит снова автоматически каждые 4 секунды.'
              : 'Честный знак принят WB — заказ можно передавать в доставку.',
      })
      if (item.status === 'error') {
        setMarkingListKind('errors')
      }
    } catch (err) {
      noticeFail('Проверка ЧЗ', err, 'Не удалось проверить Честный знак в WB')
    } finally {
      setVerifyingChzOrderId(null)
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
      if (pendingChzCount > 0) {
        setModal({
          kind: 'block',
          title: 'WB ещё проверяет Честный знак',
          message:
            'Заказы уже в «Готовые», стикеры напечатаны. Кнопка станет зелёной, ' +
            'когда WB примет коды без ошибок. Если в ЛК WB код отклонён — он появится в «Ошибки ЧЗ».',
        })
        return
      }
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
      message:
        `Передать в доставку ${ready.length} готовых заказов?\n\n` +
        'Далее выберите пункт отгрузки (СЦ/ПВЗ) и дату — они применятся ко всем заказам.',
      confirmLabel: 'Далее',
      onConfirm: () => {
        setModal(null)
        openDeliveryModal(
          'Параметры отгрузки WB',
          `Пункт отгрузки и дата будут применены ко всем ${ready.length} заказам.`,
          (shipping, printWin) => void runSendAllReadyToDelivery(ready, shipping, printWin),
        )
      },
    })
  }

  async function runSendAllReadyToDelivery(
    ready: AssemblyOrder[],
    shipping: DeliveryShippingParams,
    printWin: Window | null,
  ) {
    if (!data) return
    setError('')
    setLoading(true)
    let delivered = 0
    const errors: string[] = []
    const printedSupplyIds = new Set<string>()
    const qrErrors: string[] = []

    for (const order of ready) {
      try {
        const result = await sendOrderToDelivery(id, order.id, shipping)
        delivered += 1
        if (result.wb_supply_id && !printedSupplyIds.has(result.wb_supply_id)) {
          const printResult = await printSupplyBarcodeAfterDelivery(result, printWin)
          if (printResult.channel) {
            printedSupplyIds.add(result.wb_supply_id)
          } else if (printResult.error) {
            qrErrors.push(printResult.error)
          }
        }
      } catch (err) {
        errors.push(err instanceof Error ? err.message : `WB #${order.wb_order_id}`)
      }
    }

    if (delivered > 0) {
      noticeOk(`Шаг 4: передано в доставку ${delivered} из ${ready.length}`, 'В доставку')
      setStage('complete')
      await load({ stageKey: 'complete', silent: false })
      void refreshMarkingStatus()
    }
    if (errors.length > 0) {
      showError('Доставка', errors[0])
    } else if (qrErrors.length > 0) {
      showError(
        'QR поставки',
        `Заказы переданы в доставку. QR не напечатан для ${qrErrors.length} поставок — «Печать QR» в списке поставок.`,
      )
    }
    closePrintHolder(printWin)
    setLoading(false)
  }

  async function runDeliverSupply(
    supply: AssemblySupply,
    shipping: DeliveryShippingParams,
    printWin: Window | null,
    options?: { force?: boolean },
  ) {
    if (!id) return
    setError('')
    setLoading(true)
    try {
      const result = await deliverSupply(supply.id, shipping, options)
      if (result.supply_barcode_file) {
        setPrintHolderMessage(printWin, 'Загрузка QR поставки…')
        const channel = await printSupplySticker(result.supply_barcode_file, true, printWin)
        if (channel === 'bridge') {
          setBridgeOk(true)
        }
      } else {
        closePrintHolder(printWin)
      }
      noticeOk(
        options?.force
          ? `Поставка WB ${supply.wb_supply_id} принудительно передана в доставку`
          : `Поставка WB ${supply.wb_supply_id} (${supply.warehouse_name}) передана в доставку`,
        'Поставка',
      )
      setSelectedMoveIds(new Set())
      setStage('complete')
      await load({ stageKey: 'complete', silent: false })
      void refreshMarkingStatus()
    } catch (err) {
      closePrintHolder(printWin)
      noticeFail('Поставка', err, 'Ошибка передачи поставки в доставку')
    } finally {
      setLoading(false)
    }
  }

  function handleDeliverSupply(supply: AssemblySupply) {
    if (!supply.can_deliver) {
      setModal({
        kind: 'block',
        title: 'Поставка не готова',
        message: 'В поставке есть неотсканированные заказы или ошибки ЧЗ.',
      })
      return
    }
    if (markingQueueBlocked) {
      setModal({
        kind: 'block',
        title: 'Сначала закройте ошибки ЧЗ',
        message: 'Есть заказы с отклонённым Честным знаком.',
      })
      return
    }
    openDeliveryModal(
      'Передача поставки в доставку',
      `Поставка WB ${supply.wb_supply_id}\nСклад: ${supply.warehouse_name}\nЗаказов: ${supply.orders_count}`,
      (shipping, printWin) => void runDeliverSupply(supply, shipping, printWin),
      supply.wb_supply_id,
    )
  }

  function handleForceDeliverSupply(supply: AssemblySupply) {
    if (markingQueueBlocked) {
      setModal({
        kind: 'block',
        title: 'Сначала закройте ошибки ЧЗ',
        message: 'Есть заказы с отклонённым Честным знаком.',
      })
      return
    }
    setModal({
      kind: 'confirm',
      title: 'Принудительная передача в доставку',
      message:
        `Поставка WB ${supply.wb_supply_id} (${supply.warehouse_name}).\n\n` +
        'Передать в доставку только собранные заказы в CRM? Заказы, уже отправленные через ЛК WB ' +
        'или без стикера в CRM, не будут учитываться и не заблокируют отправку.\n\n' +
        'Продолжить?',
      confirmLabel: 'Да, передать принудительно',
      onConfirm: () => {
        setModal(null)
        openDeliveryModal(
          'Принудительная передача поставки',
          `Поставка WB ${supply.wb_supply_id}\nСклад: ${supply.warehouse_name}`,
          (shipping, printWin) => void runDeliverSupply(supply, shipping, printWin, { force: true }),
          supply.wb_supply_id,
        )
      },
    })
  }

  function toggleMoveOrder(orderId: number) {
    setSelectedMoveIds((prev) => {
      const next = new Set(prev)
      if (next.has(orderId)) next.delete(orderId)
      else next.add(orderId)
      return next
    })
  }

  function handleMoveSingleOrder(order: AssemblyOrder) {
    void startMoveOrders([order.id])
  }

  async function startMoveOrders(orderIds: number[]) {
    if (!id || orderIds.length === 0) return
    setError('')
    setLoading(true)
    try {
      const result = await fetchMoveSupplyTargets(id, orderIds)
      const targets = result.targets ?? []
      if (targets.length === 0) {
        setModal({
          kind: 'confirm',
          title: 'Новая поставка WB',
          message:
            'В ЛК WB нет другой пустой поставки. Создать новую и перенести туда заказ без товара?\n\nЗаполненные чужие поставки не предлагаем — WB ответит 409 (другой склад / тип груза / B2B). Собранные заказы останутся в текущей поставке.',
          confirmLabel: 'Создать и перенести',
          onConfirm: () => {
            setModal(null)
            void runMoveOrders(orderIds)
          },
        })
        return
      }
      setMovePicker({ orderIds, targets })
    } catch (err) {
      noticeFail('Перенос в поставку', err, 'Не удалось получить поставки из ЛК WB')
    } finally {
      setLoading(false)
    }
  }

  async function runMoveOrders(orderIds: number[], wbSupplyId?: string) {
    if (!id || orderIds.length === 0) return
    setError('')
    setLoading(true)
    try {
      const result = await moveOrdersToNewSupply(id, orderIds, wbSupplyId)
      setSelectedMoveIds(new Set())
      setMovePicker(null)
      setMarkingListKind(null)
      noticeOk(result.message, 'Перенос в поставку')
      await load({ stageKey: 'confirm', silent: false })
      void refreshMarkingStatus()
    } catch (err) {
      noticeFail('Перенос в поставку', err, 'Ошибка переноса в поставку WB')
    } finally {
      setLoading(false)
    }
  }

  function handleMoveSelectedOrders() {
    const ids = Array.from(selectedMoveIds)
    if (ids.length === 0) return
    void startMoveOrders(ids)
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
    scanBusyRef.current = true
    barcodeApiInFlightRef.current = true
    setScanBusy(true)
    scanRef.current?.blur()

    const orderList = data?.orders ?? []
    const localMarkingOrder = findLocalMarkingOrder(barcode, orderList)
    const localPrintOrder = findLocalReadyPrintOrder(barcode, orderList)
    let optimisticMarking = false
    let optimisticPrinted = false
    let printWin: Window | null = null

    if (localMarkingOrder) {
      optimisticMarking = true
      const localSticker = stickerPayloadForOrder(localMarkingOrder)
      openMarkingScan(
        { ...localMarkingOrder, sticker_file: localSticker } as unknown as PrintOrder,
      )
      scanBusyRef.current = false
      setScanBusy(false)
    } else if (localPrintOrder) {
      const localSticker = stickerPayloadForOrder(localPrintOrder)
      printWin = openPrintHolder()
      optimisticPrinted = true
      void finishPrint(
        { ...localPrintOrder, sticker_file: localSticker } as PrintOrder,
        printWin,
      )
    }

    try {
      const result = await scanOrderBarcode(id, barcode)
      const needsMarking = result.action === 'await_marking'

      if (needsMarking) {
        cacheOrderSticker(result.order)
        if (!optimisticMarking && shouldOpenMarkingForOrder(result.order.id)) {
          openMarkingScan(
            result.order,
            result.message ||
              `Заказ WB #${result.order.wb_order_id} — отсканируйте Честный знак`,
          )
        }
        closePrintHolder(printWin)
        scanBusyRef.current = false
        setScanBusy(false)
        void refreshMarkingStatus()
        return
      }

      if (optimisticMarking) {
        resetScanFlow(true)
      }

      if (!optimisticPrinted) {
        if (!printWin) {
          printWin = openPrintHolder()
        }
        try {
          await finishPrint(result.order, printWin)
        } catch (printErr) {
          closePrintHolder(printWin)
          throw printErr
        }
      }
      void refreshMarkingStatus()
      void load({ silent: true })
    } catch (err) {
      if (!optimisticPrinted) {
        closePrintHolder(printWin)
      }
      const errOrder =
        err instanceof ApiError && err.order && typeof err.order === 'object'
          ? (err.order as AssemblyOrder)
          : undefined
      const errNeedsMarking = errOrder ? orderNeedsMarkingScan(errOrder) : false
      const keepMarkingUi = markingLockRef.current || errNeedsMarking

      if (
        keepMarkingUi &&
        errOrder &&
        shouldOpenMarkingForOrder(errOrder.id) &&
        !autoPrintedOrderIdsRef.current.has(errOrder.id)
      ) {
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
        showScanError(
          err instanceof Error
            ? err.message
            : 'Стикер уже напечатан — заказ в «Готовые».',
          'Стикер уже напечатан',
          () => resetScanFlow(true),
        )
        resetScanFlow(true)
        return
      }

      if (err instanceof ApiError && err.code === 'not_in_pick_list') {
        showScanError(
          'Баркода нет в листе подбора! Обновите лист подбора или проверьте штрихкод.',
          'Баркода нет в листе подбора',
          () => {
            if (keepMarkingUi || markingLockRef.current) {
              focusMarkingInput()
            } else {
              resetScanFlow()
            }
          },
        )
        if (keepMarkingUi || markingLockRef.current) {
          focusMarkingInput()
        }
        return
      }

      const barcodeErrMsg = assemblyErrorMessage(err, 'Ошибка сканирования баркода')
      showScanError(
        barcodeErrMsg,
        assemblyScanErrorTitle(err, 'Ошибка сканирования баркода'),
        () => {
          if (keepMarkingUi || markingLockRef.current) {
            focusMarkingInput()
          } else {
            scanRef.current?.focus()
          }
        },
      )
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
    const orderSnapshot = pendingOrderRef.current ?? pendingOrder
    if (!id || !code || !orderSnapshot) return
    if (markingSubmitBusyRef.current) return

    const quickError = quickMarkingCodeCheck(code)
    if (quickError) {
      showScanError(quickError, 'Ошибка сканирования ЧЗ', () => focusMarkingInput())
      return
    }

    const orderId = orderSnapshot.id

    markingSubmitBusyRef.current = true
    setError('')
    markingBufferRef.current = ''
    setMarkingValue('')
    resetScanFlow(true)
    releaseBarcodeForNextScan()

    const sticker = stickerPayloadForOrder(orderSnapshot)
    const shouldAutoPrint = canAutoPrintOrder(orderSnapshot as AssemblyOrder)

    if (shouldAutoPrint) {
      if (!sticker) {
        markingSubmitBusyRef.current = false
        showScanError(
          `WB не отдал стикер для заказа #${orderSnapshot.wb_order_id}. Дождитесь фоновой подгрузки или нажмите «Подтянуть стикеры».`,
          'Стикер не загружен',
          () => focusMarkingInput(),
        )
        openMarkingScan(orderSnapshot)
        return
      }

      markAutoPrinted(orderId)
      cacheOrderSticker({ id: orderId, sticker_file: sticker })
      setStickerPreview(sticker)
      setLastPrinted(orderSnapshot as unknown as AssemblyOrder)
      preloadFbsSticker(sticker)
      const printWin = warmFbsPrintWindow()
      window.requestAnimationFrame(() => {
        releaseBarcodeForNextScan()
        void printSticker(sticker, printWin, () => releaseBarcodeForNextScan())
          .then(() => {
            flashPrintOk()
            releaseBarcodeForNextScan()
          })
          .catch((printErr) => {
            showScanError(
              printErr instanceof Error ? printErr.message : 'Стикер не напечатан',
              'Стикер не напечатан',
              () => releaseBarcodeForNextScan(),
            )
          })
      })
    }

    void bindMarking(id, orderId, code)
      .then(() => {
        void refreshMarkingStatus()
        void load({ silent: true })
        void runMarkingVerify({ silent: true })
      })
      .catch((err) => {
        if (err instanceof ApiError && err.code === 'already_printed') {
          void refreshMarkingStatus()
          void load({ silent: true })
          return
        }
        const markingErrMsg = assemblyErrorMessage(
          err,
          'Стикер напечатан, но CRM не приняла код ЧЗ. Проверьте «Ошибки ЧЗ».',
          orderSnapshot,
        )
        showScanError(
          markingErrMsg,
          assemblyScanErrorTitle(err, 'Ошибка ЧЗ'),
          () => focusBarcodeInput(),
        )
        void refreshMarkingStatus()
        void load({ silent: true })
      })
      .finally(() => {
        markingSubmitBusyRef.current = false
      })
  }

  async function handleReplaceOrderFromList(order: AssemblyOrder) {
    if (!id) return
    setLoading(true)
    setError('')
    try {
      const result = await replaceOrderItem(id, order.id)
      noticeOk(result.message, 'Замена товара')
      setMarkingListKind(null)
      await refreshMarkingStatus()
      await load({ silent: true })
    } catch (err) {
      showError('Замена товара', assemblyErrorMessage(err, 'Ошибка замены товара', order))
    } finally {
      setLoading(false)
    }
  }

  async function handleResetAssemblyMarking(orderIds?: number[]) {
    if (!id) return
    const count = orderIds?.length ?? markingStatus.in_assembly.filter((o) => o.requires_marking).length
    if (count < 1) {
      showError('Сброс ЧЗ', 'Нет заказов с ЧЗ для сброса')
      return
    }
    const label =
      count === 1
        ? 'Сбросить ЧЗ у выбранного заказа?\n\nКод будет удалён из CRM и WB. Повторите скан баркода и DataMatrix.'
        : `Сбросить ЧЗ у ${count} заказов?\n\nКоды будут удалены из CRM и WB. Повторите скан баркода и DataMatrix.`
    if (!window.confirm(label)) return

    setLoading(true)
    setError('')
    try {
      const result = await resetAssemblyMarking(id, orderIds)
      noticeOk(result.message, 'Сброс ЧЗ')
      setMarkingStatus((prev) => ({
        ...prev,
        in_assembly_count: result.in_assembly_count,
        ready_count: result.ready_count,
        errors_count: result.errors_count,
      }))
      await refreshMarkingStatus()
      await load({ silent: true })
      resetScanFlow()
    } catch (err) {
      noticeFail('Сброс ЧЗ', err, 'Не удалось сбросить ЧЗ')
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
      noticeOk(result.message, 'Замена товара')
      resetScanFlow(true)
      await refreshMarkingStatus()
      await load({ silent: true })
    } catch (err) {
      showError('Замена товара', assemblyErrorMessage(err, 'Ошибка замены товара', pendingOrder))
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
  const assemblyReady = data?.assembly_ready ?? data?.assembly_eligible
  const assemblyPending = data?.assembly_pending ?? 0
  const sellerName = data?.seller?.company_name ?? 'Сборка FBS'

  function stageCount(key: string): number {
    if (key === 'confirm') return counts.in_picking ?? 0
    if (key === 'complete') return counts.in_delivery ?? 0
    if (key === 'new') return counts.new ?? assemblyReady ?? 0
    return counts.new ?? 0
  }

  const ordersBusy = refreshing || syncing || togglingWarehouseId !== null
  const bulkAssemblyCount = assemblyReady ?? 0
  const displayPickLists = pickListPreviews.length > 0
    ? pickListPreviews
    : data?.active_pick_lists?.length
      ? data.active_pick_lists
      : data?.active_pick_list
        ? [data.active_pick_list]
        : []
  const displayPickListTotal = displayPickLists.reduce(
    (sum, list) => sum + (list.total_quantity || 0),
    0,
  )
  const hasPickLists = displayPickLists.some((list) => list.items?.length)
  const pickListStageOrders =
    stage === 'confirm'
      ? displayPickListTotal
      : assemblyReady ?? counts.new ?? 0
  const canDownloadPickList =
    stage === 'confirm' &&
    ((counts.in_picking ?? 0) > 0 || hasPickLists || pickListStageOrders > 0)
  const orders = data?.orders ?? []
  const missingStickersCount = orders.filter(
    (order) => (order.wb_supplier_status || '').trim() === 'confirm' && !order.has_sticker,
  ).length
  const deliverySupplies = data?.delivery_supplies ?? []
  const activeSupplies = data?.active_supplies ?? []
  const movableOrdersCount = orders.filter((order) => order.can_move_to_new_supply).length
  const readyOrders = markingStatus.ready
  const readyToDeliverCount = readyOrders.filter((order) => orderCanDeliver(order)).length
  const pendingChzCount = readyOrders.filter((order) => orderChzPending(order)).length
  const needsChzVerifyCount = readyOrders.filter((order) => orderNeedsChzVerify(order)).length
  const waitingWbCount = pendingChzCount || needsChzVerifyCount
  const deliveryUnlocked = assemblyDeliveryUnlocked(markingStatus)
  const showDeliverButton = stage === 'confirm' && readyOrders.length > 0
  const markingQueueBlocked = stage === 'confirm' && markingStatus.errors_count > 0
  const lastPrintedFresh =
    lastPrinted &&
    (readyOrders.find((order) => order.id === lastPrinted.id) ||
      markingStatus.errors.find((order) => order.id === lastPrinted.id) ||
      lastPrinted)
  const lastPrintedCanDeliver = Boolean(
    lastPrintedFresh && orderCanDeliver(lastPrintedFresh) && !markingQueueBlocked,
  )
  const markingInProgress = markingUiOpen
  const currentWorkflowStep = resolveWorkflowStep(
    stage,
    scanPhase,
    !markingInProgress &&
      (deliveryUnlocked || lastPrintedCanDeliver),
  )
  const markingListOrders =
    markingListKind === 'errors'
      ? markingStatus.errors
      : markingListKind === 'ready'
        ? markingStatus.ready
        : markingListKind === 'in_assembly'
          ? markingStatus.in_assembly
          : []

  const stageSupplies: AssemblySupply[] =
    stage === 'confirm'
      ? activeSupplies
      : stage === 'complete'
        ? deliverySupplies
        : []
  const forceDeliverSupplies = stageSupplies.filter((supply) => supply.can_force_deliver)
  const groupedBySupply = stage === 'confirm' || stage === 'complete'
  const supplyOrderIds = new Set(
    stageSupplies.flatMap((supply) => (supply.orders ?? []).map((order) => order.id)),
  )
  const unassignedOrders = groupedBySupply
    ? orders.filter((order) => !supplyOrderIds.has(order.id))
    : orders
  const hiddenRestorableOrders = data?.hidden_restorable_orders ?? []
  const groupedVisibleCount =
    stageSupplies.reduce((sum, supply) => sum + (supply.orders?.length ?? 0), 0)
    + unassignedOrders.length
  const useGroupedLayout = groupedBySupply && groupedVisibleCount > 0 && (
    stage === 'complete'
      ? stageSupplies.length >= 1
      : stageSupplies.length > 1
  )
  const tableColSpan = stage === 'confirm' ? 11 : 10

  function isOrderCancelled(order: AssemblyOrder): boolean {
    return order.status === 'cancelled'
  }

  function renderOrderRow(order: AssemblyOrder) {
    const blockReason = orderBlockReason(order)
    const cancelled = isOrderCancelled(order)
    return (
      <tr
        key={order.id}
        className={assemblyOrderRowClass(order)}
      >
        {stage === 'confirm' && (
          <td>
            {order.can_move_to_new_supply ? (
              <input
                type="checkbox"
                checked={selectedMoveIds.has(order.id)}
                onChange={() => toggleMoveOrder(order.id)}
                disabled={loading}
                aria-label={`Выбрать заказ WB #${order.wb_order_id} для переноса`}
              />
            ) : null}
          </td>
        )}
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
          {cancelled ? (
            <button
              type="button"
              className="btn btn--small btn--ghost assembly-order-delete"
              onClick={() => handleDeleteOrder(order)}
              disabled={loading}
              {...uiHint('Убрать отменённый заказ из CRM и из поставки — остальные можно передать в доставку')}
            >
              Удалить из CRM
            </button>
          ) : null}
          {!cancelled && stage === 'confirm' && !order.has_sticker && (
            <button
              type="button"
              className="btn btn--small btn--primary"
              onClick={() => void handleFetchOrderSticker(order)}
              disabled={loading || stickerFetchingOrderId === order.id}
              {...uiHint('Принудительно запросить стикер FBS из WB для этого заказа')}
            >
              {stickerFetchingOrderId === order.id ? 'Стикер…' : 'Подтянуть стикер'}
            </button>
          )}
          {!cancelled && orderStickerPrinted(order) && (stage === 'confirm' || stage === 'complete') && (
            <button
              type="button"
              className="btn btn--small btn--ghost"
              onClick={() => confirmReprintSticker(order)}
              disabled={loading}
              {...uiHint('Напечатать тот же стикер ещё раз. Остаток CRM не списывается.')}
            >
              Печать стикера повторно
            </button>
          )}
          {!cancelled && showAssemblyButton(order) && stage !== 'complete' && (
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
          {!cancelled && orderCanDeliver(order) && stage === 'confirm' && (
            <span
              {...hintWrapProps(
                markingQueueBlocked
                  ? 'Сначала закройте ошибки ЧЗ'
                  : 'Добавить заказ в поставку WB',
              )}
            >
              <button
                type="button"
                className="btn btn--small btn--deliver-ready"
                onClick={() => handleSendToDelivery(order)}
                disabled={loading || markingQueueBlocked}
              >
                В доставку
              </button>
            </span>
          )}
          {!cancelled && order.can_move_to_new_supply && stage === 'confirm' && (
            <button
              type="button"
              className="btn btn--small btn--ghost"
              onClick={() => handleMoveSingleOrder(order)}
              disabled={loading}
              {...uiHint('Создать новую поставку WB и перенести неотсканированный заказ')}
            >
              Новая поставка
            </button>
          )}
          {!cancelled && (
            <button
              type="button"
              className="btn btn--small btn--ghost assembly-order-delete"
              onClick={() => handleDeleteOrder(order)}
              disabled={loading}
              {...uiHint('Убрать заказ из текущей сборки в CRM (не отмена на WB)')}
            >
              Удалить
            </button>
          )}
        </td>
      </tr>
    )
  }

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
            {bridgeOk === false && isKioskPrintMode() && (
              <span className="assembly-bridge assembly-bridge--warn" title="CRM открыт через ?print_mode=kiosk. Без флага Chrome --kiosk-printing будет диалог «Печать» и Enter.">
                {' '}· Ярлык CRM ✓ — нужен Chrome с --kiosk-printing (без диалога)
              </span>
            )}
            {buildVersion && (
              <span className="assembly-build-version" title="Версия сервера после деплоя">
                {' '}· build {buildVersion}
              </span>
            )}
            {bridgeOk === false && !isKioskPrintMode() && (
              <span className="assembly-bridge assembly-bridge--off">
                {' '}
                · Печать: Chrome — нужен Enter (
                <Link to="/print-agent">агент или ярлык kiosk</Link>)
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
          {stage === 'confirm' && (
            <button
              type="button"
              className="btn btn--secondary"
              onClick={() => void handleFetchMissingStickers()}
              disabled={loading || stickersFetching || syncing || refreshing}
              {...uiHint(
                'Загрузить стикеры FBS из WB, если заказы передали на сборку через ЛК Wildberries',
              )}
            >
              {stickersFetching
                ? 'Стикеры…'
                : missingStickersCount > 0
                  ? `Подтянуть стикеры (${missingStickersCount})`
                  : 'Подтянуть стикеры'}
            </button>
          )}
          {stage === 'confirm' && canDownloadPickList ? (
            <button
              type="button"
              className="btn btn--secondary"
              onClick={() => void handleDownloadPickListPdf()}
              disabled={loading || pickListDownloading}
              {...uiHint('Скачать актуальный лист подбора по всем заказам на сборке — отдельный PDF на каждый склад')}
            >
              {pickListDownloading
                ? 'PDF…'
                : hasPickLists
                  ? `Скачать PDF (A4) · ${displayPickLists.length > 1
                    ? `${displayPickLists.length} складов, ${displayPickListTotal} зак.`
                    : `${displayPickListTotal} зак.`}`
                  : `Скачать PDF (A4) · ${pickListStageOrders} зак.`}
            </button>
          ) : null}
          {(stage === 'new' || stage === 'confirm') && (
            <button
              type="button"
              className="btn btn--ghost"
              onClick={() => void handleOpenPickListArchive()}
              disabled={loading || pickListArchiveLoading}
              {...uiHint('Архив листов подбора за последние 30 дней — скачать PDF повторно')}
            >
              {pickListArchiveLoading ? 'Архив…' : 'Листы подбора (архив)'}
            </button>
          )}
          {stage === 'new' && bulkAssemblyCount > 0 && (
            <button
              type="button"
              className="btn btn--primary"
              onClick={handleTransferToAssembly}
              disabled={loading}
              {...uiHint('Отправить выбранные новые заказы в статус «На сборке» в WB — отдельная поставка на каждый склад')}
            >
              Передать на сборку ({bulkAssemblyCount})
            </button>
          )}
          {stage === 'confirm' && isBatchMode && hasPickLists && (
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
          {stage === 'confirm' && selectedMoveIds.size > 0 && (
            <button
              type="button"
              className="btn btn--secondary"
              onClick={handleMoveSelectedOrders}
              disabled={loading}
              {...uiHint('Создать новые поставки WB для выбранных неотсканированных заказов')}
            >
              В новую поставку ({selectedMoveIds.size})
            </button>
          )}
          {stage === 'confirm' && (
            <button
              type="button"
              className="btn btn--secondary"
              onClick={() => void handleForceVerifyChz()}
              disabled={loading || verifyingChz}
              {...uiHint('Спросить WB по всем заказам с ЧЗ: ответ «принят» или «отклонён» по каждому заказу')}
            >
              {verifyingChz ? 'Проверяем ЧЗ…' : 'Проверить все ЧЗ'}
            </button>
          )}
          {stage === 'confirm' && showDeliverButton && (
            <span
              {...hintWrapProps(
                markingQueueBlocked
                  ? 'Сначала закройте ошибки ЧЗ — кнопка станет зелёной после замены товара'
                  : deliveryUnlocked
                    ? 'WB принял ЧЗ у готовых заказов — можно передать их в доставку. Перенесённые не блокируют.'
                    : 'Кнопка красная, пока WB проверяет ЧЗ. Если в ЛК код отклонён — смотрите «Ошибки ЧЗ».',
              )}
            >
              <button
                type="button"
                className={`btn ${deliveryUnlocked ? 'btn--deliver-ready' : 'btn--deliver-wait'}`}
                onClick={handleSendAllReadyToDelivery}
                disabled={loading}
              >
                {deliveryUnlocked
                  ? `Все готовые в доставку (${readyToDeliverCount})`
                  : markingQueueBlocked
                    ? `В доставку · ошибки ЧЗ (${markingStatus.errors_count})`
                    : `В доставку · ждём WB (${waitingWbCount})`}
              </button>
            </span>
          )}
        </div>
      </header>

      {error && !data && <div className="alert alert--error">{error}</div>}
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
        <>
          <AssemblyQueuePanels
            inAssemblyCount={markingStatus.in_assembly_count}
            readyCount={markingStatus.ready_count}
            errorsCount={markingStatus.errors_count}
            onOpenList={setMarkingListKind}
          />
          {(waitingWbCount > 0 || chzVerifyNotice) && (
            <p className="assembly-chz-notice">
              {chzVerifyNotice ||
                `WB проверяет ЧЗ у ${waitingWbCount} заказ(ов). CRM спрашивает WB каждые 4 секунды — лимита попыток нет.`}
            </p>
          )}
        </>
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
            Новые заказы подтягиваются из WB в фоне каждые 2 минуты.
            {' '}
            <strong>Готово к передаче: {bulkAssemblyCount}</strong>
            {assemblyPending > 0 ? (
              <>
                {' '}
                · ждут загрузки: {assemblyPending}
              </>
            ) : null}
            .
          </p>
          <p>
            «Передать на сборку» отправляет только уже загруженные заказы — быстро,
            без лишних запросов к WB. Поставки и листы подбора создаются автоматически,
            стикеры подтягиваются в фоне. PDF — на вкладке «На сборке».
          </p>
        </section>
      )}

      {stage === 'confirm' && (
        <section className="panel assembly-step-card assembly-step-card--scan">
          <div className="assembly-picklist-head">
            <h2 className="section-title">Лист подбора</h2>
            <div className="assembly-picklist-actions">
              <button
                type="button"
                className="btn btn--secondary btn--small"
                onClick={() => void handleDownloadPickListPdf()}
                disabled={loading || pickListDownloading || !canDownloadPickList}
                {...uiHint('Скачать PDF для сборщика — доступно и после передачи заказов на сборку')}
              >
                {pickListDownloading ? 'PDF…' : 'Скачать PDF (A4)'}
              </button>
            </div>
          </div>
          <p>
            Лист формируется автоматически при «Передать на сборку».
            PDF всегда можно скачать повторно — по сохранённому списку или по текущим заказам на сборке.
          </p>
          {hasPickLists && displayPickLists.length > 0 && (
            <ul className="assembly-picklists">
              {displayPickLists.map((list) => (
                <li key={list.id || list.warehouse_name}>
                  <strong>{list.warehouse_name || `Склад #${list.wb_warehouse_id ?? list.id}`}</strong>
                  {' — '}
                  {list.total_quantity} зак.
                  {list.items?.length ? (
                    <>
                      {' '}
                      <button
                        type="button"
                        className="btn btn--ghost btn--small"
                        onClick={() => void handleDownloadPickListPdf(list)}
                      >
                        PDF
                      </button>
                    </>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {stage === 'confirm' && isBatchMode && (
        <BatchBindPanel
          sellerId={id}
          disabled={!hasPickLists}
          onBound={async (immediateVerify?: boolean) => {
            if (immediateVerify) void runMarkingVerify()
            await refreshMarkingStatus()
            await load({ silent: true })
          }}
          onSuccess={(message) => noticeOk(message, 'Связка ЧЗ')}
          onError={(message) => showError('Связка ЧЗ', message)}
        />
      )}

      {stage === 'confirm' && !isBatchMode && bridgeOk !== true && (
        <p className="assembly-kiosk-hint" role="status">
          {isKioskPrintMode()
            ? 'Если после скана окно «Печать» с кнопкой — Chrome без --kiosk-printing. Закройте все chrome.exe в диспетчере задач. Ярлык должен содержать --user-data-dir=%LOCALAPPDATA%\\FulfillmentCRM-Print — тогда одна вкладка CRM, без github/WB.'
            : 'Стикер печатается через окно Chrome — нужен Enter. Для печати без Enter: ярлык с --user-data-dir и --kiosk-printing или агент печати.'}
        </p>
      )}

      {stage === 'confirm' && !isBatchMode && (
        <section
          ref={scanPanelRef}
          className={`panel assembly-scan-panel assembly-scan-live${markingInProgress ? ' assembly-scan-panel--marking-active' : ''}`}
        >
          <div hidden={markingInProgress}>
            <h2 className="section-title">Сканируйте баркод заказа</h2>
            <p className="assembly-scan-hint">
              Курсор уже в поле. При необходимости скачайте PDF листа подбора в шапке.
              После скана товара с ЧЗ сразу откроется поле DataMatrix, затем печать стикера.
            </p>
            <form onSubmit={handleBarcodeSubmit}>
              <input
                ref={scanRef}
                type="text"
                className="assembly-scan-input"
                value={scanValue}
                onChange={(e) => setScanValue(e.target.value)}
                onKeyDown={handleScanKeyDown}
                placeholder={scanBusy ? 'Проверяем заказ…' : 'Баркод заказа...'}
                autoComplete="off"
                autoFocus={!markingInProgress}
                readOnly={scanBusy}
                tabIndex={markingInProgress ? -1 : 0}
              />
            </form>
          </div>
          <div hidden={!markingInProgress}>
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
              DataMatrix с упаковки. Стикер печатается сразу; привязка ЧЗ в WB и проверка — в фоне.
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
                autoFocus={markingInProgress}
                tabIndex={markingInProgress ? 0 : -1}
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

          {lastPrintedFresh && !markingInProgress && (
            <div className={`assembly-last-print${lastPrintedCanDeliver ? ' assembly-last-print--ready' : ''}`}>
              <p>
                <strong>Шаг 4:</strong> WB #{lastPrintedFresh.wb_order_id}{' '}
                {lastPrintedCanDeliver
                  ? 'готов к доставке'
                  : orderChzPending(lastPrintedFresh)
                    ? 'ждёт ответ WB по ЧЗ'
                    : 'пока нельзя в доставку'}
              </p>
              <span
                {...hintWrapProps(
                  lastPrintedCanDeliver
                    ? 'Добавить заказ в поставку WB и перевести в доставку'
                    : markingQueueBlocked
                      ? 'Сначала закройте ошибки ЧЗ'
                      : 'Кнопка станет зелёной, когда WB примет ЧЗ',
                )}
              >
                <button
                  type="button"
                  className={`btn btn--small ${lastPrintedCanDeliver ? 'btn--deliver-ready' : 'btn--deliver-wait'}`}
                  onClick={() => {
                    if (!lastPrintedCanDeliver) {
                      handleSendAllReadyToDelivery()
                      return
                    }
                    if (lastPrintedFresh) handleSendToDelivery(lastPrintedFresh)
                  }}
                  disabled={loading}
                >
                  Подтвердить и в доставку
                </button>
              </span>
            </div>
          )}

          {stickerPreview && (
            <div className="assembly-sticker-preview">
              <img src={`data:image/png;base64,${stickerPreview}`} alt="Стикер FBS" />
              {(lastPrintedFresh || lastPrinted) && (
                <button
                  type="button"
                  className="btn btn--secondary btn--small assembly-sticker-preview__reprint"
                  onClick={() => confirmReprintSticker((lastPrintedFresh || lastPrinted)!)}
                  disabled={loading}
                  {...uiHint('Напечатать этот стикер ещё раз — остаток не списывается')}
                >
                  Повторная печать
                </button>
              )}
            </div>
          )}
        </section>
      )}

      {stage === 'confirm' && showDeliverButton && !markingInProgress && (
        <section className={`panel assembly-step-card assembly-step-card--delivery${deliveryUnlocked ? '' : ' assembly-step-card--delivery-wait'}`}>
          <h2 className="section-title">
            {deliveryUnlocked
              ? `Шаг 4 — готово к доставке: ${readyToDeliverCount}`
              : 'Шаг 4 — ждём ответ WB по Честному знаку'}
          </h2>
          <p>
            {deliveryUnlocked
              ? 'WB принял все ЧЗ без ошибок. Зелёная кнопка «В доставку» в шапке.'
              : 'Заказы уже в «Готовые». Кнопка красная, пока WB не примет все ЧЗ. Зелёная — можно отгружать.'}
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
          Листы подбора формируются автоматически при «Передать на сборку» — отдельно на каждый склад.
        </p>
        {(data?.warehouses?.length ?? 0) === 0 ? (
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

      <div className={`assembly-grid${stage === 'confirm' ? ' assembly-grid--scan' : ''}`}>
        {stage === 'confirm' && hiddenRestorableOrders.length > 0 && (
          <section className="panel assembly-hidden-orders">
            <h2 className="section-title">
              Удалённые из сборки ({hiddenRestorableOrders.length})
            </h2>
            <p className="assembly-scan-hint">
              Эти заказы скрыты кнопкой «Удалить», но ещё есть в ЛК WB (новые или на сборке).
              Восстановите, чтобы снова сканировать баркод и печатать стикер — иначе поставка WB
              может не уйти в доставку.
            </p>
            <table className="assembly-table">
              <thead>
                <tr>
                  <th>WB ID</th>
                  <th>Баркод</th>
                  <th>Этап WB</th>
                  <th>Стикер</th>
                  <th>Действие</th>
                </tr>
              </thead>
              <tbody>
                {hiddenRestorableOrders.map((order) => (
                  <tr key={`hidden-${order.id}`}>
                    <td>{order.wb_order_id}</td>
                    <td><code>{order.barcode}</code></td>
                    <td>{order.wb_stage_display || order.status_display}</td>
                    <td>{order.has_sticker ? formatStickerNumber(order) || '✓' : '—'}</td>
                    <td>
                      {!order.has_sticker && (
                        <button
                          type="button"
                          className="btn btn--small btn--primary"
                          onClick={() => void handleFetchOrderSticker(order)}
                          disabled={loading || stickerFetchingOrderId === order.id}
                          {...uiHint('Принудительно запросить стикер FBS из WB')}
                        >
                          {stickerFetchingOrderId === order.id ? 'Стикер…' : 'Подтянуть стикер'}
                        </button>
                      )}
                      <button
                        type="button"
                        className="btn btn--small btn--ghost"
                        onClick={() => handleRestoreOrder(order)}
                        disabled={loading}
                        {...uiHint('Вернуть заказ в сборку и подтянуть стикер из WB при необходимости')}
                      >
                        Восстановить
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )}

        <section className={`panel assembly-orders-panel${ordersBusy ? ' assembly-orders-panel--busy' : ''}`}>
          <h2 className="section-title">
            {groupedBySupply ? `Заказы по поставкам (${stageCount(stage)})` : `Заказы (${stageCount(stage)})`}
            {stage === 'confirm' && movableOrdersCount > 0 && (
              <span className="assembly-orders-panel__hint">
                {' '}· можно перенести: {movableOrdersCount}
              </span>
            )}
            {ordersBusy && <span className="assembly-orders-panel__status">обновление…</span>}
          </h2>
          {groupedBySupply && (
            <p className="assembly-scan-hint">
              {stage === 'confirm'
                ? 'Только заказы на сборке в WB. Нет товара — «Перенести». Заказы «Новые» — на вкладке «Новые» или «Удалённые из сборки» ниже.'
                : 'QR поставки — кнопка «Печать QR» в шапке каждой поставки.'}
            </p>
          )}
          <table className="assembly-table">
            <thead>
              <tr>
                {stage === 'confirm' && <th aria-label="Выбор для переноса" />}
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
                  <td colSpan={tableColSpan} className="assembly-table__empty">
                    {refreshing || syncing
                      ? 'Загрузка заказов…'
                      : stage === 'confirm'
                        ? (counts.in_picking ?? 0) > 0
                          ? 'Заказы на сборке не попали в таблицу — нажмите «Обновить заказы»'
                          : 'Все заказы собраны — см. зелёный счётчик «Готовые»'
                        : 'Нет заказов на этой вкладке'}
                  </td>
                </tr>
              ) : useGroupedLayout ? (
                <>
                  {stageSupplies.map((supply) => {
                    const supplyOrders = sortAssemblyOrders(supply.orders ?? [])
                    const movableIds = supplyOrders
                      .filter((order) => order.can_move_to_new_supply)
                      .map((order) => order.id)
                    return (
                      <Fragment key={`supply-${supply.id}`}>
                        <tr className="assembly-supply-group-row">
                          <td colSpan={tableColSpan}>
                            <div className="assembly-supply-group-header">
                              <div>
                                <strong>{supply.wb_supply_id}</strong>
                                {supply.created_at && (
                                  <span className="assembly-supply-group-header__meta">
                                    {' · '}
                                    {formatSupplyCreatedAt(supply.created_at)}
                                  </span>
                                )}
                                <span className="assembly-supply-group-header__meta">
                                  {' · '}
                                  {supply.warehouse_name || `Склад #${supply.wb_warehouse_id ?? '—'}`}
                                  {' · '}
                                  {supply.orders_count} зак.
                                  {stage === 'confirm' && (
                                    supply.can_deliver ? (
                                      <span className="assembly-supply-status assembly-supply-status--ready">
                                        {' · '}Готова к доставке
                                      </span>
                                    ) : (
                                      <span className="assembly-supply-status">
                                        {' · '}На сборке
                                      </span>
                                    )
                                  )}
                                </span>
                              </div>
                              <div className="assembly-supply-group-header__actions">
                                {stage === 'confirm' && supply.can_deliver && (
                                  <span
                                    {...hintWrapProps(
                                      markingQueueBlocked
                                        ? 'Сначала закройте ошибки ЧЗ'
                                        : 'Передать всю поставку в доставку на WB',
                                    )}
                                  >
                                    <button
                                      type="button"
                                      className="btn btn--small btn--deliver-ready"
                                      onClick={() => handleDeliverSupply(supply)}
                                      disabled={loading || markingQueueBlocked}
                                    >
                                      В доставку
                                    </button>
                                  </span>
                                )}
                                {stage === 'confirm' && movableIds.length > 0 && (
                                  <button
                                    type="button"
                                    className="btn btn--small btn--ghost"
                                    onClick={() => void startMoveOrders(movableIds)}
                                    disabled={loading}
                                    {...uiHint('Перенести все неготовые заказы поставки в другую пустую поставку WB')}
                                  >
                                    Перенести неготовые ({movableIds.length})
                                  </button>
                                )}
                                {stage === 'complete' && (
                                  <button
                                    type="button"
                                    className="btn btn--small btn--primary"
                                    onClick={() => void handlePrintSupplyBarcode(supply.id, supply.wb_supply_id)}
                                    disabled={loading}
                                  >
                                    Печать QR
                                  </button>
                                )}
                              </div>
                            </div>
                          </td>
                        </tr>
                        {supplyOrders.map((order) => renderOrderRow(order))}
                      </Fragment>
                    )
                  })}
                  {unassignedOrders.length > 0 && (
                    <>
                      <tr className="assembly-supply-group-row">
                        <td colSpan={tableColSpan}>
                          <strong>Вне поставок</strong>
                          <span className="assembly-supply-group-header__meta">
                            {' '}({unassignedOrders.length})
                          </span>
                        </td>
                      </tr>
                      {sortAssemblyOrders(unassignedOrders).map((order) => renderOrderRow(order))}
                    </>
                  )}
                </>
              ) : (
                sortAssemblyOrders(orders).map((order) => renderOrderRow(order))
              )}
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

      {stage === 'confirm' && forceDeliverSupplies.length > 0 && (
        <section className="panel assembly-force-deliver">
          <h2 className="section-title">Принудительная передача в доставку</h2>
          <p className="assembly-force-deliver__hint">
            Поставка не уходит в доставку из‑за заказов, которых нет в сборке CRM
            (например, уже отправленных через ЛК WB). Можно передать только собранные заказы.
          </p>
          <div className="assembly-force-deliver__actions">
            {forceDeliverSupplies.map((supply) => (
              <button
                key={`force-deliver-${supply.id}`}
                type="button"
                className="btn btn--danger-outline"
                disabled={loading || markingQueueBlocked}
                onClick={() => handleForceDeliverSupply(supply)}
                {...uiHint('Пропустить «призрачные» заказы и передать собранные в доставку WB')}
              >
                Принудительно: WB {supply.wb_supply_id}
                {supply.warehouse_name ? ` · ${supply.warehouse_name}` : ''}
              </button>
            ))}
          </div>
        </section>
      )}

      {modal && (
        <AssemblyModal modal={modal} onClose={() => setModal(null)} loading={loading} />
      )}

      {deliveryModal && (
        <DeliveryDestinationModal
          sellerId={id}
          title={deliveryModal.title}
          message={deliveryModal.message}
          wbSupplyId={deliveryModal.wbSupplyId}
          loading={loading}
          onClose={() => {
            closePrintHolder(deliveryModal.printWin)
            setDeliveryModal(null)
          }}
          onConfirm={(shipping) => deliveryModal.onConfirm(shipping, deliveryModal.printWin)}
        />
      )}

      {markingListKind && (
        <AssemblyQueueListModal
          kind={markingListKind}
          orders={markingListOrders}
          loading={loading}
          onClose={() => setMarkingListKind(null)}
          onReplace={markingListKind === 'errors' ? (order) => void handleReplaceOrderFromList(order) : undefined}
          onResetMarking={
            markingListKind === 'in_assembly'
              ? (orderIds) => void handleResetAssemblyMarking(orderIds)
              : undefined
          }
          onReprint={
            markingListKind === 'ready'
              ? (order) => confirmReprintSticker(order, () => setMarkingListKind(null))
              : undefined
          }
          onDeliver={
            markingListKind === 'ready'
              ? (order) => {
                  if (!orderCanDeliver(order)) {
                    showError('Доставка', orderBlockReason(order) || 'Заказ пока нельзя передать в доставку')
                    return
                  }
                  setMarkingListKind(null)
                  handleSendToDelivery(order)
                }
              : undefined
          }
          onMove={
            markingListKind === 'in_assembly'
              ? (order) => {
                  setMarkingListKind(null)
                  handleMoveSingleOrder(order)
                }
              : undefined
          }
          onVerifyChz={(order) => void handleVerifyOrderChz(order)}
          verifyingChzOrderId={verifyingChzOrderId}
        />
      )}

      {movePicker && (
        <div className="assembly-modal-backdrop" role="presentation" onClick={() => setMovePicker(null)}>
          <div
            className="assembly-modal assembly-move-picker"
            role="dialog"
            aria-labelledby="move-supply-title"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 id="move-supply-title">Куда перенести заказ</h2>
            <p className="assembly-modal__message">
              Выберите пустую поставку из ЛК WB или создайте новую. Заполненные чужие поставки WB
              отклоняет с ошибкой 409. Собранные заказы останутся в текущей — их можно сразу
              отгрузить.
            </p>
            <ul className="assembly-move-picker__list">
              {movePicker.targets.map((target) => (
                <li key={target.wb_supply_id}>
                  <button
                    type="button"
                    className="btn btn--secondary assembly-move-picker__item"
                    disabled={loading}
                    onClick={() => void runMoveOrders(movePicker.orderIds, target.wb_supply_id)}
                  >
                    <strong>WB {target.wb_supply_id}</strong>
                    <span>
                      {target.warehouse_name || 'Склад'}
                      {target.orders_count ? ` · заказов: ${target.orders_count}` : ' · пустая'}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
            <div className="assembly-modal__actions">
              <button
                type="button"
                className="btn btn--primary"
                disabled={loading}
                onClick={() => void runMoveOrders(movePicker.orderIds)}
              >
                Создать новую поставку
              </button>
              <button
                type="button"
                className="btn btn--ghost"
                disabled={loading}
                onClick={() => setMovePicker(null)}
              >
                Отмена
              </button>
            </div>
          </div>
        </div>
      )}

      {pickListArchiveOpen && (
        <div className="assembly-modal-backdrop" role="presentation" onClick={() => setPickListArchiveOpen(false)}>
          <div
            className="assembly-modal panel"
            role="dialog"
            aria-labelledby="pick-list-archive-title"
            onClick={(event) => event.stopPropagation()}
          >
            <h2 id="pick-list-archive-title" className="section-title">Листы подбора — архив (30 дней)</h2>
            {pickListArchive.length === 0 ? (
              <p className="assembly-scan-hint">За последние 30 дней завершённых листов нет.</p>
            ) : (
              <table className="assembly-table">
                <thead>
                  <tr>
                    <th>№</th>
                    <th>Склад</th>
                    <th>Дата</th>
                    <th>Позиций</th>
                    <th>Заказов</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {pickListArchive.map((pickList) => (
                    <tr key={pickList.id}>
                      <td>{pickList.id}</td>
                      <td>{pickList.warehouse_name || `Склад #${pickList.wb_warehouse_id ?? '—'}`}</td>
                      <td>{formatSupplyCreatedAt(pickList.created_at)}</td>
                      <td>{pickList.items_count}</td>
                      <td>{pickList.total_quantity}</td>
                      <td>
                        <button
                          type="button"
                          className="btn btn--small btn--secondary"
                          onClick={() => void handleDownloadArchivePickList(pickList.id)}
                          disabled={pickListArchiveLoading}
                        >
                          PDF
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <div className="assembly-modal__actions">
              <button
                type="button"
                className="btn btn--ghost"
                onClick={() => setPickListArchiveOpen(false)}
              >
                Закрыть
              </button>
            </div>
          </div>
        </div>
      )}

    </>
  )
}

