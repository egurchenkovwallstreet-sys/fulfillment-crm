import { useEffect, useState, type FormEvent } from 'react'
import {
  applySellerTariff,
  fetchPriceGroups,
  fetchSellerPricing,
  type PriceGroupItem,
  type SellerManageItem,
  type SellerPricingSummary,
} from '../api/sellerAdmin'
import './SellerTariffModal.css'

type Scope = 'all' | 'group'

type Props = {
  seller: SellerManageItem
  onClose: () => void
  onApplied: (message: string) => void
}

function formatPrice(value: string | null | undefined): string {
  if (!value) return '—'
  return `${Number(value).toLocaleString('ru-RU', { minimumFractionDigits: 0, maximumFractionDigits: 2 })} ₽`
}

export function SellerTariffModal({ seller, onClose, onApplied }: Props) {
  const [scope, setScope] = useState<Scope>('all')
  const [price, setPrice] = useState('')
  const [priceGroupId, setPriceGroupId] = useState<number | ''>('')
  const [assignGroup, setAssignGroup] = useState(false)
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

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    const normalized = price.replace(',', '.').trim()
    if (!normalized || Number.isNaN(Number(normalized))) {
      setError('Укажите корректный тариф')
      return
    }
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
          <button type="button" className="btn btn--ghost" onClick={onClose} aria-label="Закрыть">
            ✕
          </button>
        </div>

        {loading && <p>Загрузка…</p>}
        {error && <div className="dashboard-sync-msg dashboard-sync-msg--error">{error}</div>}

        {!loading && summary && (
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

            <form className="seller-tariff-modal__form" onSubmit={handleSubmit}>
              <div className="seller-tariff-modal__scopes">
                <button
                  type="button"
                  className={`seller-tariff-modal__scope${scope === 'all' ? ' seller-tariff-modal__scope--active' : ''}`}
                  onClick={() => setScope('all')}
                >
                  На все товары
                </button>
                <button
                  type="button"
                  className={`seller-tariff-modal__scope${scope === 'group' ? ' seller-tariff-modal__scope--active' : ''}`}
                  onClick={() => setScope('group')}
                  disabled={priceGroups.length === 0}
                >
                  На ценовую группу
                </button>
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
                  ? `Будет обновлено товаров: ${affectedCount}. Индивидуальный тариф имеет приоритет над групповым.`
                  : groupSummary
                    ? `В группе сейчас ${groupSummary.product_count} товар(ов)${
                        groupSummary.tariff ? `, тариф ${formatPrice(groupSummary.tariff)}` : ''
                      }.${assignGroup && summary.ungrouped_count > 0 ? ` + ${summary.ungrouped_count} без группы.` : ''}`
                    : 'В этой группе пока нет товаров — включите назначение группы или задайте общий тариф.'}
              </p>

              <div className="seller-tariff-modal__actions">
                <button type="button" className="btn btn--ghost" onClick={onClose}>
                  Отмена
                </button>
                <button type="submit" className="btn btn--primary" disabled={saving || affectedCount === 0}>
                  {saving ? 'Сохранение…' : 'Применить тариф'}
                </button>
              </div>
            </form>
          </>
        )}
      </div>
    </div>
  )
}
