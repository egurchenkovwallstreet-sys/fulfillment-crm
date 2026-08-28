import { useCallback, useEffect, useState, type FormEvent } from 'react'
import {
  createPriceGroup,
  deletePriceGroup,
  fetchPriceGroups,
  updatePriceGroup,
  type PriceGroupItem,
} from '../../api/sellerAdmin'
import './OwnerLayout.css'

function formatPrice(value: string): string {
  return `${Number(value).toLocaleString('ru-RU', { minimumFractionDigits: 0, maximumFractionDigits: 2 })} ₽`
}

export function OwnerPricingPage() {
  const [groups, setGroups] = useState<PriceGroupItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [name, setName] = useState('')
  const [price, setPrice] = useState('')
  const [sortOrder, setSortOrder] = useState('0')
  const [creating, setCreating] = useState(false)
  const [editId, setEditId] = useState<number | null>(null)
  const [editName, setEditName] = useState('')
  const [editPrice, setEditPrice] = useState('')
  const [editSort, setEditSort] = useState('0')
  const [saving, setSaving] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setGroups(await fetchPriceGroups())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка загрузки')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  async function handleCreate(e: FormEvent) {
    e.preventDefault()
    if (!name.trim()) return
    setCreating(true)
    setMessage('')
    setError('')
    try {
      await createPriceGroup({
        name: name.trim(),
        processing_price: price || '0',
        sort_order: Number(sortOrder) || 0,
      })
      setName('')
      setPrice('')
      setSortOrder('0')
      setMessage(`Группа «${name.trim()}» создана`)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка создания')
    } finally {
      setCreating(false)
    }
  }

  function startEdit(group: PriceGroupItem) {
    setEditId(group.id)
    setEditName(group.name)
    setEditPrice(group.processing_price)
    setEditSort(String(group.sort_order))
  }

  async function handleSaveEdit(e: FormEvent) {
    e.preventDefault()
    if (editId === null) return
    setSaving(true)
    setError('')
    setMessage('')
    try {
      await updatePriceGroup(editId, {
        name: editName.trim(),
        processing_price: editPrice,
        sort_order: Number(editSort) || 0,
      })
      setEditId(null)
      setMessage('Группа сохранена')
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка сохранения')
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete(group: PriceGroupItem) {
    if (!window.confirm(`Удалить группу «${group.name}»? Товары останутся без группы.`)) return
    setError('')
    setMessage('')
    try {
      await deletePriceGroup(group.id)
      setMessage(`Группа «${group.name}» удалена`)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка удаления')
    }
  }

  return (
    <>
      <header className="topbar">
        <div>
          <h1>Ценовые группы</h1>
          <p>Группы для тарифов обработки — используются при назначении тарифа селлеру</p>
        </div>
        <button type="button" className="btn btn--ghost" onClick={load} disabled={loading}>
          Обновить
        </button>
      </header>

      {error && <div className="dashboard-sync-msg dashboard-sync-msg--error">{error}</div>}
      {message && <div className="dashboard-sync-msg dashboard-sync-msg--ok">{message}</div>}

      <section className="panel">
        <h2 className="section-title">Новая группа</h2>
        <form className="owner-pricing-form" onSubmit={handleCreate}>
          <label>
            Название
            <input type="text" value={name} onChange={(e) => setName(e.target.value)} required />
          </label>
          <label>
            Цена за ед., ₽
            <input type="number" step="0.01" min="0" value={price} onChange={(e) => setPrice(e.target.value)} />
          </label>
          <label>
            Порядок
            <input type="number" min="0" value={sortOrder} onChange={(e) => setSortOrder(e.target.value)} />
          </label>
          <button type="submit" className="btn btn--primary" disabled={creating}>
            {creating ? 'Создание…' : 'Создать'}
          </button>
        </form>
      </section>

      <section className="panel">
        <h2 className="section-title">Список групп</h2>
        {loading && groups.length === 0 && <p>Загрузка…</p>}
        {!loading && groups.length === 0 && <p>Групп пока нет.</p>}
        {groups.length > 0 && (
          <div className="sellers-table-scroll">
            <table className="owner-staff-table owner-pricing-table">
              <thead>
                <tr>
                  <th>Название</th>
                  <th>Цена за ед.</th>
                  <th>Порядок</th>
                  <th>Действия</th>
                </tr>
              </thead>
              <tbody>
                {groups.map((group) =>
                  editId === group.id ? (
                    <tr key={group.id}>
                      <td colSpan={4}>
                        <form className="owner-pricing-form" onSubmit={handleSaveEdit}>
                          <input type="text" value={editName} onChange={(e) => setEditName(e.target.value)} required />
                          <input
                            type="number"
                            step="0.01"
                            min="0"
                            value={editPrice}
                            onChange={(e) => setEditPrice(e.target.value)}
                          />
                          <input
                            type="number"
                            min="0"
                            value={editSort}
                            onChange={(e) => setEditSort(e.target.value)}
                          />
                          <button type="submit" className="btn btn--primary btn--sm" disabled={saving}>
                            {saving ? '…' : 'Сохранить'}
                          </button>
                          <button type="button" className="btn btn--ghost btn--sm" onClick={() => setEditId(null)}>
                            Отмена
                          </button>
                        </form>
                      </td>
                    </tr>
                  ) : (
                    <tr key={group.id}>
                      <td>
                        <strong>{group.name}</strong>
                      </td>
                      <td>{formatPrice(group.processing_price)}</td>
                      <td>{group.sort_order}</td>
                      <td>
                        <button type="button" className="btn btn--ghost btn--sm" onClick={() => startEdit(group)}>
                          Изменить
                        </button>
                        <button type="button" className="btn btn--ghost btn--sm" onClick={() => handleDelete(group)}>
                          Удалить
                        </button>
                      </td>
                    </tr>
                  ),
                )}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  )
}
