import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  applySellerProductTariffs,
  fetchSellerProductTariffs,
  fetchSellersManage,
  type SellerManageItem,
  type SellerProductTariffItem,
  type SellerProductTariffsApplyPayload,
} from '../../api/sellerAdmin'
import { uiHint } from '../../utils/uiHint'
import './OwnerLayout.css'
import './OwnerSellerTariffsPage.css'

type DimensionDraft = {
  length: string
  width: string
  height: string
}

function formatPrice(value: string | null | undefined): string {
  if (!value) return '—'
  return `${Number(value).toLocaleString('ru-RU', { minimumFractionDigits: 0, maximumFractionDigits: 2 })} ₽`
}

function formatDimension(value: string | null | undefined): string {
  if (!value) return ''
  return String(Number(value))
}

function priceDraft(item: SellerProductTariffItem): string {
  if (item.individual_price != null && item.individual_price !== '') {
    return String(item.individual_price)
  }
  if (item.effective_price != null && item.effective_price !== '') {
    return String(item.effective_price)
  }
  return ''
}

function dimensionDraftFromItem(item: SellerProductTariffItem): DimensionDraft {
  return {
    length: formatDimension(item.length_cm),
    width: formatDimension(item.width_cm),
    height: formatDimension(item.height_cm),
  }
}

function dimensionsMatch(item: SellerProductTariffItem, draft: DimensionDraft): boolean {
  return (
    formatDimension(item.length_cm) === draft.length.trim()
    && formatDimension(item.width_cm) === draft.width.trim()
    && formatDimension(item.height_cm) === draft.height.trim()
  )
}

export function OwnerSellerTariffsPage() {
  const [sellers, setSellers] = useState<SellerManageItem[]>([])
  const [sellerId, setSellerId] = useState<number | ''>('')
  const [items, setItems] = useState<SellerProductTariffItem[]>([])
  const [pricingMode, setPricingMode] = useState<'per_unit' | 'per_liter'>('per_unit')
  const [companyName, setCompanyName] = useState('')
  const [drafts, setDrafts] = useState<Record<number, string>>({})
  const [dimensionDrafts, setDimensionDrafts] = useState<Record<number, DimensionDraft>>({})
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [bulkPrice, setBulkPrice] = useState('')
  const [bulkLength, setBulkLength] = useState('')
  const [bulkWidth, setBulkWidth] = useState('')
  const [bulkHeight, setBulkHeight] = useState('')
  const [loadingSellers, setLoadingSellers] = useState(true)
  const [loadingItems, setLoadingItems] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  useEffect(() => {
    let cancelled = false
    void (async () => {
      setLoadingSellers(true)
      try {
        const list = await fetchSellersManage()
        if (!cancelled) {
          setSellers(list.filter((seller) => seller.is_active))
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Не удалось загрузить селлеров')
        }
      } finally {
        if (!cancelled) setLoadingSellers(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const applyItemsResponse = useCallback((data: Awaited<ReturnType<typeof fetchSellerProductTariffs>>) => {
    setItems(data.items)
    setPricingMode(data.pricing_mode)
    setCompanyName(data.company_name)
    const nextDrafts: Record<number, string> = {}
    const nextDimensions: Record<number, DimensionDraft> = {}
    for (const item of data.items) {
      nextDrafts[item.id] = priceDraft(item)
      nextDimensions[item.id] = dimensionDraftFromItem(item)
    }
    setDrafts(nextDrafts)
    setDimensionDrafts(nextDimensions)
    setSelected(new Set())
    setBulkPrice('')
    setBulkLength('')
    setBulkWidth('')
    setBulkHeight('')
  }, [])

  const loadItems = useCallback(async (id: number) => {
    setLoadingItems(true)
    setError('')
    setMessage('')
    try {
      const data = await fetchSellerProductTariffs(id)
      applyItemsResponse(data)
    } catch (err) {
      setItems([])
      setError(err instanceof Error ? err.message : 'Не удалось загрузить товары')
    } finally {
      setLoadingItems(false)
    }
  }, [applyItemsResponse])

  useEffect(() => {
    if (!sellerId) {
      setItems([])
      setDrafts({})
      setDimensionDrafts({})
      setSelected(new Set())
      return
    }
    void loadItems(sellerId)
  }, [sellerId, loadItems])

  const allSelected = items.length > 0 && selected.size === items.length

  const dirtyPriceIds = useMemo(() => {
    return items.filter((item) => {
      const draft = (drafts[item.id] ?? '').trim()
      const saved = item.individual_price ?? ''
      return draft !== String(saved)
    }).map((item) => item.id)
  }, [items, drafts])

  const dirtyDimensionIds = useMemo(() => {
    return items.filter((item) => {
      const draft = dimensionDrafts[item.id] ?? dimensionDraftFromItem(item)
      return !dimensionsMatch(item, draft)
    }).map((item) => item.id)
  }, [items, dimensionDrafts])

  function toggleAll(checked: boolean) {
    if (!checked) {
      setSelected(new Set())
      return
    }
    setSelected(new Set(items.map((item) => item.id)))
  }

  function toggleOne(id: number, checked: boolean) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (checked) next.add(id)
      else next.delete(id)
      return next
    })
  }

  function setDraft(id: number, value: string) {
    setDrafts((prev) => ({ ...prev, [id]: value }))
  }

  function setDimensionDraft(id: number, field: keyof DimensionDraft, value: string) {
    setDimensionDrafts((prev) => ({
      ...prev,
      [id]: {
        ...(prev[id] ?? { length: '', width: '', height: '' }),
        [field]: value,
      },
    }))
  }

  async function savePayload(payload: SellerProductTariffsApplyPayload, successMsg: string) {
    if (!sellerId) return
    setSaving(true)
    setError('')
    setMessage('')
    try {
      const result = await applySellerProductTariffs(sellerId, payload)
      applyItemsResponse(result)
      setMessage(successMsg)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось сохранить')
    } finally {
      setSaving(false)
    }
  }

  function parsePrice(value: string, label: string): string | null {
    const normalized = value.replace(',', '.').trim()
    if (!normalized || Number.isNaN(Number(normalized)) || Number(normalized) < 0) {
      setError(`Укажите корректную цену: ${label}`)
      return null
    }
    return normalized
  }

  function parseDimension(value: string, label: string): string | null {
    const normalized = value.replace(',', '.').trim()
    if (!normalized || Number.isNaN(Number(normalized)) || Number(normalized) <= 0) {
      setError(`Укажите корректный габарит: ${label}`)
      return null
    }
    return normalized
  }

  function buildDimensionUpdate(productId: number, draft: DimensionDraft) {
    const length = parseDimension(draft.length, 'длина')
    const width = parseDimension(draft.width, 'ширина')
    const height = parseDimension(draft.height, 'высота')
    if (!length || !width || !height) return null
    return {
      product_id: productId,
      length_cm: length,
      width_cm: width,
      height_cm: height,
    }
  }

  async function handleBulkApplyPrice() {
    if (!selected.size) {
      setError('Отметьте товары галочками')
      return
    }
    const price = parsePrice(bulkPrice, 'для выбранных')
    if (!price) return
    const updates = [...selected].map((product_id) => ({ product_id, price }))
    await savePayload({ updates }, `Тариф ${formatPrice(price)} применён к ${updates.length} товарам`)
  }

  async function handleBulkApplyDimensions() {
    if (!selected.size) {
      setError('Отметьте товары галочками')
      return
    }
    const length = parseDimension(bulkLength, 'длина')
    const width = parseDimension(bulkWidth, 'ширина')
    const height = parseDimension(bulkHeight, 'высота')
    if (!length || !width || !height) return
    await savePayload(
      {
        dimension_bulk: {
          product_ids: [...selected],
          length_cm: length,
          width_cm: width,
          height_cm: height,
        },
      },
      `Габариты ${length}×${width}×${height} см применены к ${selected.size} товарам`,
    )
  }

  async function handleSaveRowPrice(item: SellerProductTariffItem) {
    const price = parsePrice(drafts[item.id] ?? '', item.barcode)
    if (!price) return
    await savePayload({ updates: [{ product_id: item.id, price }] }, `Тариф для ${item.barcode} сохранён`)
  }

  async function handleSaveRowDimensions(item: SellerProductTariffItem) {
    const draft = dimensionDrafts[item.id] ?? dimensionDraftFromItem(item)
    const update = buildDimensionUpdate(item.id, draft)
    if (!update) return
    await savePayload(
      { dimension_updates: [update] },
      `Габариты для ${item.barcode} сохранены`,
    )
  }

  async function handleSaveDirtyPrices() {
    const updates = dirtyPriceIds
      .map((id) => {
        const price = parsePrice(drafts[id] ?? '', `#${id}`)
        return price ? { product_id: id, price } : null
      })
      .filter(Boolean) as { product_id: number; price: string }[]
    if (!updates.length) {
      setError('Нет изменений тарифов для сохранения')
      return
    }
    await savePayload({ updates }, `Сохранено тарифов: ${updates.length}`)
  }

  async function handleSaveDirtyDimensions() {
    const dimension_updates = dirtyDimensionIds
      .map((id) => buildDimensionUpdate(id, dimensionDrafts[id] ?? dimensionDraftFromItem(items.find((item) => item.id === id)!)))
      .filter(Boolean) as NonNullable<ReturnType<typeof buildDimensionUpdate>>[]
    if (!dimension_updates.length) {
      setError('Нет изменений габаритов для сохранения')
      return
    }
    await savePayload({ dimension_updates }, `Сохранено габаритов: ${dimension_updates.length}`)
  }

  return (
    <>
      <header className="topbar">
        <div>
          <h1>Тарифы и габариты</h1>
          <p>
            Тариф отгрузки и габариты для хранения (литры) по каждому баркоду. Можно задать одни габариты сразу нескольким товарам.
          </p>
        </div>
      </header>

      {error && <div className="dashboard-sync-msg dashboard-sync-msg--error">{error}</div>}
      {message && <div className="dashboard-sync-msg dashboard-sync-msg--ok">{message}</div>}

      <section className="panel owner-tariffs-panel">
        <div className="owner-tariffs-toolbar">
          <label className="owner-tariffs-field">
            <span>Селлер</span>
            <select
              value={sellerId}
              onChange={(event) => setSellerId(event.target.value ? Number(event.target.value) : '')}
              disabled={loadingSellers || saving}
            >
              <option value="">Выберите селлера…</option>
              {sellers.map((seller) => (
                <option key={seller.id} value={seller.id}>
                  {seller.company_name}
                </option>
              ))}
            </select>
          </label>

          {sellerId && (
            <div className="owner-tariffs-meta">
              <span>{companyName}</span>
              <span className="owner-tariffs-meta__mode">
                Режим отгрузки: {pricingMode === 'per_liter' ? 'по объёму' : 'за единицу'}
              </span>
              <span>{items.length} товар(ов)</span>
            </div>
          )}
        </div>

        {sellerId && (
          <>
            <div className="owner-tariffs-bulk">
              <label className="owner-tariffs-bulk__check">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={(event) => toggleAll(event.target.checked)}
                  disabled={!items.length || saving}
                />
                <span>Выбрать все</span>
              </label>
              <input
                type="text"
                inputMode="decimal"
                className="owner-tariffs-bulk__price"
                placeholder="Цена для выбранных, ₽"
                value={bulkPrice}
                onChange={(event) => setBulkPrice(event.target.value)}
                disabled={saving}
              />
              <button
                type="button"
                className="btn btn--secondary"
                onClick={() => void handleBulkApplyPrice()}
                disabled={saving || selected.size === 0}
                {...uiHint('Применить одну цену ко всем отмеченным товарам')}
              >
                {saving ? 'Сохранение…' : `Тариф (${selected.size})`}
              </button>
              {dirtyPriceIds.length > 0 && (
                <button
                  type="button"
                  className="btn btn--primary"
                  onClick={() => void handleSaveDirtyPrices()}
                  disabled={saving}
                >
                  Сохранить тарифы ({dirtyPriceIds.length})
                </button>
              )}
            </div>

            <div className="owner-tariffs-bulk owner-tariffs-bulk--dimensions">
              <span className="owner-tariffs-bulk__label">Габариты для выбранных, см:</span>
              <input
                type="text"
                inputMode="decimal"
                className="owner-tariffs-dim-input"
                placeholder="Д"
                value={bulkLength}
                onChange={(event) => setBulkLength(event.target.value)}
                disabled={saving}
                aria-label="Длина"
              />
              <span className="owner-tariffs-dim-sep">×</span>
              <input
                type="text"
                inputMode="decimal"
                className="owner-tariffs-dim-input"
                placeholder="Ш"
                value={bulkWidth}
                onChange={(event) => setBulkWidth(event.target.value)}
                disabled={saving}
                aria-label="Ширина"
              />
              <span className="owner-tariffs-dim-sep">×</span>
              <input
                type="text"
                inputMode="decimal"
                className="owner-tariffs-dim-input"
                placeholder="В"
                value={bulkHeight}
                onChange={(event) => setBulkHeight(event.target.value)}
                disabled={saving}
                aria-label="Высота"
              />
              <button
                type="button"
                className="btn btn--secondary"
                onClick={() => void handleBulkApplyDimensions()}
                disabled={saving || selected.size === 0}
                {...uiHint('Применить одни габариты ко всем отмеченным баркодам — для начисления хранения')}
              >
                {saving ? 'Сохранение…' : `Габариты (${selected.size})`}
              </button>
              {dirtyDimensionIds.length > 0 && (
                <button
                  type="button"
                  className="btn btn--primary"
                  onClick={() => void handleSaveDirtyDimensions()}
                  disabled={saving}
                >
                  Сохранить габариты ({dirtyDimensionIds.length})
                </button>
              )}
            </div>
          </>
        )}

        {!sellerId && !loadingSellers && (
          <p className="owner-tariffs-empty">Выберите селлера, чтобы увидеть список товаров.</p>
        )}

        {sellerId && loadingItems && <p>Загрузка товаров…</p>}

        {sellerId && !loadingItems && items.length === 0 && (
          <p className="owner-tariffs-empty">У селлера нет товаров с ячейкой в CRM.</p>
        )}

        {sellerId && !loadingItems && items.length > 0 && (
          <div className="owner-tariffs-table-wrap">
            <table className="owner-tariffs-table">
              <thead>
                <tr>
                  <th aria-label="Выбор" />
                  <th>Ячейка</th>
                  <th>Баркод</th>
                  <th>Товар</th>
                  <th>Размер</th>
                  <th>Д, см</th>
                  <th>Ш, см</th>
                  <th>В, см</th>
                  <th>Литры</th>
                  <th>Тариф</th>
                  <th>Цена, ₽</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {items.map((item) => {
                  const isPriceDirty = dirtyPriceIds.includes(item.id)
                  const isDimensionDirty = dirtyDimensionIds.includes(item.id)
                  const dim = dimensionDrafts[item.id] ?? dimensionDraftFromItem(item)
                  return (
                    <tr
                      key={item.id}
                      className={
                        isPriceDirty || isDimensionDirty ? 'owner-tariffs-table__row--dirty' : undefined
                      }
                    >
                      <td>
                        <input
                          type="checkbox"
                          checked={selected.has(item.id)}
                          onChange={(event) => toggleOne(item.id, event.target.checked)}
                          disabled={saving}
                          aria-label={`Выбрать ${item.barcode}`}
                        />
                      </td>
                      <td>{item.cell_number || '—'}</td>
                      <td><code>{item.barcode}</code></td>
                      <td>
                        <div className="owner-tariffs-product-name">{item.name || item.vendor_code || '—'}</div>
                        {item.vendor_code && item.name ? (
                          <div className="owner-tariffs-product-meta">{item.vendor_code}</div>
                        ) : null}
                      </td>
                      <td>{item.tech_size || '—'}</td>
                      <td>
                        <input
                          type="text"
                          inputMode="decimal"
                          className="owner-tariffs-dim-input"
                          value={dim.length}
                          onChange={(event) => setDimensionDraft(item.id, 'length', event.target.value)}
                          disabled={saving}
                        />
                      </td>
                      <td>
                        <input
                          type="text"
                          inputMode="decimal"
                          className="owner-tariffs-dim-input"
                          value={dim.width}
                          onChange={(event) => setDimensionDraft(item.id, 'width', event.target.value)}
                          disabled={saving}
                        />
                      </td>
                      <td>
                        <input
                          type="text"
                          inputMode="decimal"
                          className="owner-tariffs-dim-input"
                          value={dim.height}
                          onChange={(event) => setDimensionDraft(item.id, 'height', event.target.value)}
                          disabled={saving}
                        />
                      </td>
                      <td className="owner-tariffs-volume">
                        {item.volume_liters ? `${item.volume_liters} л` : '—'}
                      </td>
                      <td>{formatPrice(item.effective_price)}</td>
                      <td>
                        <input
                          type="text"
                          inputMode="decimal"
                          className="owner-tariffs-row-price"
                          value={drafts[item.id] ?? ''}
                          onChange={(event) => setDraft(item.id, event.target.value)}
                          onKeyDown={(event) => {
                            if (event.key === 'Enter') {
                              event.preventDefault()
                              void handleSaveRowPrice(item)
                            }
                          }}
                          disabled={saving}
                          placeholder="0"
                        />
                      </td>
                      <td className="owner-tariffs-actions">
                        <button
                          type="button"
                          className="btn btn--small btn--ghost"
                          onClick={() => void handleSaveRowDimensions(item)}
                          disabled={saving || !isDimensionDirty}
                        >
                          Габ.
                        </button>
                        <button
                          type="button"
                          className="btn btn--small btn--ghost"
                          onClick={() => void handleSaveRowPrice(item)}
                          disabled={saving || !isPriceDirty}
                        >
                          ₽
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  )
}
