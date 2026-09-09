import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  applySellerProductTariffs,
  fetchSellerProductTariffs,
  fetchSellersManage,
  type SellerManageItem,
  type SellerProductTariffItem,
} from '../../api/sellerAdmin'
import { uiHint } from '../../utils/uiHint'
import './OwnerLayout.css'
import './OwnerSellerTariffsPage.css'

function formatPrice(value: string | null | undefined): string {
  if (!value) return '—'
  return `${Number(value).toLocaleString('ru-RU', { minimumFractionDigits: 0, maximumFractionDigits: 2 })} ₽`
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

export function OwnerSellerTariffsPage() {
  const [sellers, setSellers] = useState<SellerManageItem[]>([])
  const [sellerId, setSellerId] = useState<number | ''>('')
  const [items, setItems] = useState<SellerProductTariffItem[]>([])
  const [pricingMode, setPricingMode] = useState<'per_unit' | 'per_liter'>('per_unit')
  const [companyName, setCompanyName] = useState('')
  const [drafts, setDrafts] = useState<Record<number, string>>({})
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [bulkPrice, setBulkPrice] = useState('')
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

  const loadItems = useCallback(async (id: number) => {
    setLoadingItems(true)
    setError('')
    setMessage('')
    try {
      const data = await fetchSellerProductTariffs(id)
      setItems(data.items)
      setPricingMode(data.pricing_mode)
      setCompanyName(data.company_name)
      const nextDrafts: Record<number, string> = {}
      for (const item of data.items) {
        nextDrafts[item.id] = priceDraft(item)
      }
      setDrafts(nextDrafts)
      setSelected(new Set())
      setBulkPrice('')
    } catch (err) {
      setItems([])
      setError(err instanceof Error ? err.message : 'Не удалось загрузить товары')
    } finally {
      setLoadingItems(false)
    }
  }, [])

  useEffect(() => {
    if (!sellerId) {
      setItems([])
      setDrafts({})
      setSelected(new Set())
      return
    }
    void loadItems(sellerId)
  }, [sellerId, loadItems])

  const allSelected = items.length > 0 && selected.size === items.length

  const dirtyIds = useMemo(() => {
    return items.filter((item) => {
      const draft = (drafts[item.id] ?? '').trim()
      const saved = item.individual_price ?? ''
      return draft !== String(saved)
    }).map((item) => item.id)
  }, [items, drafts])

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

  async function saveUpdates(updates: { product_id: number; price: string }[], successMsg: string) {
    if (!sellerId || !updates.length) return
    setSaving(true)
    setError('')
    setMessage('')
    try {
      const result = await applySellerProductTariffs(sellerId, updates)
      setItems(result.items)
      setPricingMode(result.pricing_mode)
      const nextDrafts: Record<number, string> = {}
      for (const item of result.items) {
        nextDrafts[item.id] = priceDraft(item)
      }
      setDrafts(nextDrafts)
      setSelected(new Set())
      setBulkPrice('')
      setMessage(successMsg)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось сохранить тарифы')
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

  async function handleBulkApply() {
    if (!selected.size) {
      setError('Отметьте товары галочками')
      return
    }
    const price = parsePrice(bulkPrice, 'для выбранных')
    if (!price) return
    const updates = [...selected].map((product_id) => ({ product_id, price }))
    await saveUpdates(updates, `Тариф ${formatPrice(price)} применён к ${updates.length} товарам`)
  }

  async function handleSaveRow(item: SellerProductTariffItem) {
    const price = parsePrice(drafts[item.id] ?? '', item.barcode)
    if (!price) return
    await saveUpdates([{ product_id: item.id, price }], `Тариф для ${item.barcode} сохранён`)
  }

  async function handleSaveDirty() {
    const updates = dirtyIds
      .map((id) => {
        const price = parsePrice(drafts[id] ?? '', `#${id}`)
        return price ? { product_id: id, price } : null
      })
      .filter(Boolean) as { product_id: number; price: string }[]
    if (!updates.length) {
      setError('Нет изменений для сохранения')
      return
    }
    await saveUpdates(updates, `Сохранено тарифов: ${updates.length}`)
  }

  return (
    <>
      <header className="topbar">
        <div>
          <h1>Тарифы по товарам</h1>
          <p>
            Тариф отгрузки за единицу по каждому баркоду. Показаны только товары с ячейкой в CRM.
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
              onClick={() => void handleBulkApply()}
              disabled={saving || selected.size === 0}
              {...uiHint('Применить одну цену ко всем отмеченным товарам')}
            >
              {saving ? 'Сохранение…' : `Применить к выбранным (${selected.size})`}
            </button>
            {dirtyIds.length > 0 && (
              <button
                type="button"
                className="btn btn--primary"
                onClick={() => void handleSaveDirty()}
                disabled={saving}
              >
                Сохранить изменения ({dirtyIds.length})
              </button>
            )}
          </div>
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
                  <th>Группа</th>
                  <th>Текущий тариф</th>
                  <th>Новая цена, ₽</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {items.map((item) => {
                  const isDirty = dirtyIds.includes(item.id)
                  return (
                    <tr key={item.id} className={isDirty ? 'owner-tariffs-table__row--dirty' : undefined}>
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
                      <td>{item.price_group_name || '—'}</td>
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
                              void handleSaveRow(item)
                            }
                          }}
                          disabled={saving}
                          placeholder="0"
                        />
                      </td>
                      <td>
                        <button
                          type="button"
                          className="btn btn--small btn--ghost"
                          onClick={() => void handleSaveRow(item)}
                          disabled={saving || !isDirty}
                        >
                          Сохранить
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
