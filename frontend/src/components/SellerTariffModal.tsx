import { useEffect, useState, type FormEvent } from 'react'
import {
  applySellerLiterTariff,
  applySellerTariff,
  fetchPriceGroups,
  fetchSellerPricing,
  type PriceGroupItem,
  type SellerLiterTariffs,
  type SellerManageItem,
  type SellerPricingSummary,
} from '../api/sellerAdmin'
import { hintWrapProps, uiHint } from '../utils/uiHint'
import './SellerTariffModal.css'

type Scope = 'all' | 'group'
type TariffKind = 'unit' | 'liter'

type Props = {
  seller: SellerManageItem
  onClose: () => void
  onApplied: (message: string) => void
}

function formatPrice(value: string | null | undefined): string {
  if (!value) return '—'
  return `${Number(value).toLocaleString('ru-RU', { minimumFractionDigits: 0, maximumFractionDigits: 2 })} ₽`
}

function literDefaults(liter?: SellerLiterTariffs) {
  return {
    pricingMode: liter?.pricing_mode ?? 'per_unit',
    firstLiter: liter?.first_liter_shipment_price ?? '10',
    nextLiter: liter?.next_liter_shipment_price ?? '6',
    marking: liter?.marking_surcharge_per_unit ?? '5',
    storage: liter?.storage_tariff_per_liter_month ?? '1',
  }
}

export function SellerTariffModal({ seller, onClose, onApplied }: Props) {
  const [tariffKind, setTariffKind] = useState<TariffKind>('unit')
  const [scope, setScope] = useState<Scope>('all')
  const [price, setPrice] = useState('')
  const [priceGroupId, setPriceGroupId] = useState<number | ''>('')
  const [assignGroup, setAssignGroup] = useState(false)
  const [pricingMode, setPricingMode] = useState<'per_unit' | 'per_liter'>('per_unit')
  const [firstLiter, setFirstLiter] = useState('10')
  const [nextLiter, setNextLiter] = useState('6')
  const [markingSurcharge, setMarkingSurcharge] = useState('5')
  const [storageTariff, setStorageTariff] = useState('1')
  const [priceGroups, setPriceGroups] = useState<PriceGroupItem[]>([])
  const [summary, setSummary] = useState<SellerPricingSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError('')
      try {
        const [groups, pricing] = await Promise.all([
          fetchPriceGroups(),
          fetchSellerPricing(seller.id),
        ])
        if (cancelled) return
        setPriceGroups(groups)
        setSummary(pricing)
        if (groups.length > 0) {
          setPriceGroupId(groups[0].id)
        }
        if (pricing.common_tariff && !pricing.mixed_common_tariff) {
          setPrice(String(pricing.common_tariff))
        }
        const liter = literDefaults(pricing.liter)
        setPricingMode(liter.pricingMode)
        setFirstLiter(liter.firstLiter)
        setNextLiter(liter.nextLiter)
        setMarkingSurcharge(liter.marking)
        setStorageTariff(liter.storage)
        setTariffKind(liter.pricingMode === 'per_liter' ? 'liter' : 'unit')
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Ошибка загрузки')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [seller.id])

  const selectedGroup = priceGroups.find((group) => group.id === priceGroupId)
  const groupSummary = summary?.groups.find((group) => group.id === priceGroupId)
  const affectedCount =
    scope === 'all'
      ? summary?.product_count ?? 0
      : (groupSummary?.product_count ?? 0) + (assignGroup ? (summary?.ungrouped_count ?? 0) : 0)

  function parseDecimal(value: string, label: string): string | null {
    const normalized = value.replace(',', '.').trim()
    if (!normalized || Number.isNaN(Number(normalized))) {
      setError(`Укажите корректное значение: ${label}`)
      return null
    }
    return normalized
  }

  async function handleSubmitUnit(e: FormEvent) {
    e.preventDefault()
    const normalized = parseDecimal(price, 'тариф')
    if (!normalized) return
    if (scope === 'group' && !priceGroupId) {
      setError('Выберите ценовую группу')
      return
    }

    setSaving(true)
    setError('')
    try {
      const response = await applySellerTariff(seller.id, {
        scope,
        price: normalized,
        price_group_id: scope === 'group' ? Number(priceGroupId) : undefined,
        assign_group: scope === 'group' ? assignGroup : undefined,
      })
      setSummary(response.summary)
      const label =
        scope === 'all'
          ? `Общий тариф ${formatPrice(normalized)} применён к ${response.result.updated} товарам`
          : `Тариф ${formatPrice(normalized)} применён к ${response.result.updated} товарам группы`
      onApplied(label)
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось сохранить тариф')
    } finally {
      setSaving(false)
    }
  }

  async function handleSubmitLiter(e: FormEvent) {
    e.preventDefault()
    const first = parseDecimal(firstLiter, '1-й литр отгрузки')
    const next = parseDecimal(nextLiter, 'доп. литр отгрузки')
    const marking = parseDecimal(markingSurcharge, 'надбавка за ЧЗ')
    const storage = parseDecimal(storageTariff, 'хранение за литр/мес')
    if (!first || !next || !marking || !storage) return

    setSaving(true)
    setError('')
    try {
      const response = await applySellerLiterTariff(seller.id, {
        pricing_mode: pricingMode,
        first_liter_shipment_price: first,
        next_liter_shipment_price: next,
        marking_surcharge_per_unit: marking,
        storage_tariff_per_liter_month: storage,
      })
      setSummary(response.summary)
      onApplied(
        pricingMode === 'per_liter'
          ? 'Включена тарификация по литражу'
          : 'Включена тарификация по штукам',
      )
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось сохранить тариф')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="seller-tariff-modal" role="presentation" onClick={onClose}>
      <div
        className="seller-tariff-modal__dialog panel"
        role="dialog"
        aria-labelledby="seller-tariff-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="seller-tariff-modal__head">
          <div>
            <h2 id="seller-tariff-title" className="section-title">Тариф селлера</h2>
            <p className="seller-tariff-modal__subtitle">{seller.company_name}</p>
          </div>
          <button type="button" className="btn btn--ghost" onClick={onClose} aria-label="Закрыть" {...uiHint('Закрыть окно настройки тарифа без сохранения.')}>
            ✕
          </button>
        </div>

        {loading && <p>Загрузка…</p>}
        {error && <div className="dashboard-sync-msg dashboard-sync-msg--error">{error}</div>}

        {!loading && summary && (
          <>
            <div className="seller-tariff-modal__scopes">
              <button
                type="button"
                className={`seller-tariff-modal__scope${tariffKind === 'unit' ? ' seller-tariff-modal__scope--active' : ''}`}
                onClick={() => setTariffKind('unit')}
                {...uiHint('Тариф за обработку одной единицы товара.')}
              >
                По штукам
              </button>
              <button
                type="button"
                className={`seller-tariff-modal__scope${tariffKind === 'liter' ? ' seller-tariff-modal__scope--active' : ''}`}
                onClick={() => setTariffKind('liter')}
                {...uiHint('Тарификация по литражу: хранение и отгрузки.')}
              >
                По литражу
              </button>
            </div>

            {tariffKind === 'unit' ? (
              <>
                <div className="seller-tariff-modal__stats">
                  <div>
                    <span className="seller-tariff-modal__stat-label">Товаров</span>
                    <strong>{summary.product_count}</strong>
                  </div>
                  <div>
                    <span className="seller-tariff-modal__stat-label">Без группы</span>
                    <strong>{summary.ungrouped_count}</strong>
                  </div>
                  <div>
                    <span className="seller-tariff-modal__stat-label">Общий тариф</span>
                    <strong>
                      {summary.mixed_common_tariff ? 'разные' : formatPrice(summary.common_tariff)}
                    </strong>
                  </div>
                </div>

                {priceGroups.length === 0 && (
                  <p className="seller-tariff-modal__hint">
                    Сначала создайте ценовые группы в Django-админке (раздел «Ценовые группы»).
                  </p>
                )}

                <form className="seller-tariff-modal__form" onSubmit={handleSubmitUnit}>
                  <div className="seller-tariff-modal__scopes">
                    <button
                      type="button"
                      className={`seller-tariff-modal__scope${scope === 'all' ? ' seller-tariff-modal__scope--active' : ''}`}
                      onClick={() => setScope('all')}
                      {...uiHint('Применить один тариф ко всем товарам селлера.')}
                    >
                      На все товары
                    </button>
                    <span {...hintWrapProps('Применить тариф только к товарам выбранной ценовой группы.')}>
                      <button
                        type="button"
                        className={`seller-tariff-modal__scope${scope === 'group' ? ' seller-tariff-modal__scope--active' : ''}`}
                        onClick={() => setScope('group')}
                        disabled={priceGroups.length === 0}
                      >
                        На ценовую группу
                      </button>
                    </span>
                  </div>

                  {scope === 'group' && (
                    <label className="seller-tariff-modal__field">
                      <span>Ценовая группа</span>
                      <select
                        value={priceGroupId}
                        onChange={(event) => setPriceGroupId(Number(event.target.value))}
                      >
                        {priceGroups.map((group) => (
                          <option key={group.id} value={group.id}>
                            {group.name} (база {formatPrice(group.processing_price)})
                          </option>
                        ))}
                      </select>
                    </label>
                  )}

                  <label className="seller-tariff-modal__field">
                    <span>Тариф за единицу, ₽</span>
                    <input
                      type="text"
                      inputMode="decimal"
                      value={price}
                      onChange={(event) => setPrice(event.target.value)}
                      placeholder="например, 35"
                      required
                    />
                  </label>

                  {scope === 'group' && summary.ungrouped_count > 0 && (
                    <label className="seller-tariff-modal__checkbox">
                      <input
                        type="checkbox"
                        checked={assignGroup}
                        onChange={(event) => setAssignGroup(event.target.checked)}
                      />
                      <span>
                        Назначить группу «{selectedGroup?.name}» товарам без группы ({summary.ungrouped_count} шт.)
                      </span>
                    </label>
                  )}

                  <p className="seller-tariff-modal__hint">
                    {scope === 'all'
                      ? `Будет обновлено товаров: ${affectedCount}.`
                      : groupSummary
                        ? `В группе сейчас ${groupSummary.product_count} товар(ов).`
                        : 'В этой группе пока нет товаров.'}
                  </p>

                  <div className="seller-tariff-modal__actions">
                    <button type="button" className="btn btn--ghost" onClick={onClose}>Отмена</button>
                    <button type="submit" className="btn btn--primary" disabled={saving || affectedCount === 0}>
                      {saving ? 'Сохранение…' : 'Применить тариф'}
                    </button>
                  </div>
                </form>
              </>
            ) : (
              <form className="seller-tariff-modal__form" onSubmit={handleSubmitLiter}>
                <label className="seller-tariff-modal__field">
                  <span>Режим тарификации</span>
                  <select
                    value={pricingMode}
                    onChange={(event) => setPricingMode(event.target.value as 'per_unit' | 'per_liter')}
                  >
                    <option value="per_unit">По штукам (система 1)</option>
                    <option value="per_liter">По литражу (система 2)</option>
                  </select>
                </label>

                <div className="seller-tariff-modal__liter-grid">
                  <label className="seller-tariff-modal__field">
                    <span>1-й литр отгрузки, ₽</span>
                    <input type="text" inputMode="decimal" value={firstLiter} onChange={(e) => setFirstLiter(e.target.value)} />
                  </label>
                  <label className="seller-tariff-modal__field">
                    <span>Каждый доп. литр, ₽</span>
                    <input type="text" inputMode="decimal" value={nextLiter} onChange={(e) => setNextLiter(e.target.value)} />
                  </label>
                  <label className="seller-tariff-modal__field">
                    <span>Надбавка за ЧЗ, ₽/шт</span>
                    <input type="text" inputMode="decimal" value={markingSurcharge} onChange={(e) => setMarkingSurcharge(e.target.value)} />
                  </label>
                  <label className="seller-tariff-modal__field">
                    <span>Хранение, ₽/л/мес</span>
                    <input type="text" inputMode="decimal" value={storageTariff} onChange={(e) => setStorageTariff(e.target.value)} />
                  </label>
                </div>

                <p className="seller-tariff-modal__hint">
                  Объём: (Д×Ш×В)/1000, округление вверх до 0,1 л. Хранение начисляется ежедневно по остатку в ячейке.
                  Отгрузка: 1-й литр + доп. литры (хвост ≤0,5 л → 0,5 л, иначе целый литр вверх).
                </p>

                <div className="seller-tariff-modal__actions">
                  <button type="button" className="btn btn--ghost" onClick={onClose}>Отмена</button>
                  <button type="submit" className="btn btn--primary" disabled={saving}>
                    {saving ? 'Сохранение…' : 'Сохранить тарифы'}
                  </button>
                </div>
              </form>
            )}
          </>
        )}
      </div>
    </div>
  )
}
