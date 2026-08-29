import { useCallback, useEffect, useState, type FormEvent } from 'react'
import {
  clearSellerOzonKeys,
  clearSellerWbToken,
  createSeller,
  deleteSeller,
  fetchSellerInvite,
  fetchSellersManage,
  saveSellerOzonKeys,
  saveSellerWbToken,
  updateSeller,
  type SellerManageItem,
} from '../api/sellerAdmin'
import { copyToClipboard } from '../utils/copyToClipboard'
import { SellerTariffModal } from '../components/SellerTariffModal'
import './SellersManagePage.css'

function inviteUrl(token: string | null): string {
  if (!token) return ''
  return `${window.location.origin}/register/${token}`
}

export function SellersManagePage() {
  const [sellers, setSellers] = useState<SellerManageItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [companyName, setCompanyName] = useState('')
  const [createWb, setCreateWb] = useState(true)
  const [createOzon, setCreateOzon] = useState(false)
  const [createWbToken, setCreateWbToken] = useState('')
  const [createOzonClientId, setCreateOzonClientId] = useState('')
  const [createOzonApiKey, setCreateOzonApiKey] = useState('')
  const [creating, setCreating] = useState(false)
  const [copiedId, setCopiedId] = useState<number | null>(null)
  const [message, setMessage] = useState('')
  const [tariffSeller, setTariffSeller] = useState<SellerManageItem | null>(null)
  const [editSeller, setEditSeller] = useState<SellerManageItem | null>(null)
  const [editName, setEditName] = useState('')
  const [editWbEnabled, setEditWbEnabled] = useState(true)
  const [editOzonEnabled, setEditOzonEnabled] = useState(false)
  const [editWbToken, setEditWbToken] = useState('')
  const [editOzonClientId, setEditOzonClientId] = useState('')
  const [editOzonApiKey, setEditOzonApiKey] = useState('')
  const [savingEdit, setSavingEdit] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setSellers(await fetchSellersManage())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка загрузки')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  function openEdit(seller: SellerManageItem) {
    setEditSeller(seller)
    setEditName(seller.company_name)
    setEditWbEnabled(seller.wb_enabled)
    setEditOzonEnabled(seller.ozon_enabled)
    setEditWbToken('')
    setEditOzonClientId(seller.ozon_client_id || '')
    setEditOzonApiKey('')
    setError('')
  }

  async function handleCreate(e: FormEvent) {
    e.preventDefault()
    if (!companyName.trim()) return
    if (!createWb && !createOzon) {
      setError('Выберите хотя бы один маркетплейс')
      return
    }
    setCreating(true)
    setMessage('')
    setError('')
    try {
      const created = await createSeller({
        company_name: companyName.trim(),
        wb_enabled: createWb,
        ozon_enabled: createOzon,
        wb_token: createWb ? createWbToken.trim() : undefined,
        ozon_client_id: createOzon ? createOzonClientId.trim() : undefined,
        ozon_api_key: createOzon ? createOzonApiKey.trim() : undefined,
      })
      setCompanyName('')
      setCreateWbToken('')
      setCreateOzonClientId('')
      setCreateOzonApiKey('')
      const extra = (created as { token_messages?: string[] }).token_messages?.join(' ')
      setMessage(
        extra
          ? `Селлер «${created.company_name}» создан. ${extra}`
          : `Селлер «${created.company_name}» создан. Скопируйте ссылку для регистрации.`,
      )
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка создания')
    } finally {
      setCreating(false)
    }
  }

  async function handleSaveEdit(e: FormEvent) {
    e.preventDefault()
    if (!editSeller) return
    if (!editWbEnabled && !editOzonEnabled) {
      setError('Оставьте хотя бы один маркетплейс')
      return
    }
    setSavingEdit(true)
    setError('')
    setMessage('')
    try {
      await updateSeller(editSeller.id, {
        company_name: editName.trim(),
        is_active: editSeller.is_active,
        wb_enabled: editWbEnabled,
        ozon_enabled: editOzonEnabled,
      })
      if (editWbEnabled && editWbToken.trim()) {
        const wb = await saveSellerWbToken(editSeller.id, editWbToken.trim())
        setMessage(wb.detail)
      }
      if (editOzonEnabled && editOzonClientId.trim() && editOzonApiKey.trim()) {
        const oz = await saveSellerOzonKeys(editSeller.id, {
          client_id: editOzonClientId.trim(),
          api_key: editOzonApiKey.trim(),
        })
        setMessage(oz.detail)
      }
      if (!editWbToken.trim() && !(editOzonApiKey.trim() && editOzonClientId.trim())) {
        setMessage('Селлер сохранён')
      }
      setEditSeller(null)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка сохранения')
    } finally {
      setSavingEdit(false)
    }
  }

  async function handleDeleteSeller() {
    if (!editSeller) return
    if (
      !window.confirm(
        `Удалить селлера «${editSeller.company_name}» навсегда?\n\nВсе товары, ячейки и история будут удалены. Это нельзя отменить.`,
      )
    ) {
      return
    }
    setSavingEdit(true)
    setError('')
    try {
      const result = await deleteSeller(editSeller.id)
      setMessage(result.detail)
      setEditSeller(null)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось удалить')
    } finally {
      setSavingEdit(false)
    }
  }

  async function copyInvite(seller: SellerManageItem) {
    setMessage('')
    try {
      let token = seller.invite_token
      if (!token) {
        const invite = await fetchSellerInvite(seller.id)
        token = invite.token
        await load()
      }
      const url = inviteUrl(token)
      await copyToClipboard(url)
      setCopiedId(seller.id)
      setMessage(`Ссылка скопирована для «${seller.company_name}»`)
      window.setTimeout(() => setCopiedId(null), 2000)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось скопировать')
    }
  }

  return (
    <>
      <header className="topbar">
        <div>
          <h1>Селлеры</h1>
          <p>Создание, API-токены, редактирование и удаление селлеров</p>
        </div>
        <button type="button" className="btn btn--ghost" onClick={load} disabled={loading}>
          Обновить
        </button>
      </header>

      {error && <div className="dashboard-sync-msg dashboard-sync-msg--error">{error}</div>}
      {message && <div className="dashboard-sync-msg dashboard-sync-msg--ok">{message}</div>}

      <section className="panel sellers-create-panel">
        <h2 className="section-title">Новый селлер</h2>
        <form className="sellers-form" onSubmit={handleCreate}>
          <div className="sellers-form__row">
            <input
              type="text"
              value={companyName}
              onChange={(e) => setCompanyName(e.target.value)}
              placeholder="ИП / название компании"
              required
            />
            <label className="sellers-mp-check">
              <input type="checkbox" checked={createWb} onChange={(e) => setCreateWb(e.target.checked)} />
              WB
            </label>
            <label className="sellers-mp-check">
              <input type="checkbox" checked={createOzon} onChange={(e) => setCreateOzon(e.target.checked)} />
              Ozon
            </label>
            <button type="submit" className="btn btn--primary" disabled={creating}>
              {creating ? 'Создание…' : 'Создать'}
            </button>
          </div>

          {createWb && (
            <div className="sellers-form__block">
              <strong>Токен WB (необязательно сейчас)</strong>
              <p className="sellers-ozon-hint">
                ЛК seller.wildberries.ru → Настройки → Доступ к API → права «Контент» и «Маркетплейс».
              </p>
              <input
                type="password"
                value={createWbToken}
                onChange={(e) => setCreateWbToken(e.target.value)}
                placeholder="Вставьте токен WB"
              />
            </div>
          )}

          {createOzon && (
            <div className="sellers-form__block">
              <strong>Ключи Ozon (необязательно сейчас)</strong>
              <p className="sellers-ozon-hint">
                seller.ozon.ru → Настройки → API-ключи → Client-Id и Api-Key.
              </p>
              <div className="sellers-form__row">
                <input
                  type="text"
                  value={createOzonClientId}
                  onChange={(e) => setCreateOzonClientId(e.target.value)}
                  placeholder="Client-Id"
                />
                <input
                  type="password"
                  value={createOzonApiKey}
                  onChange={(e) => setCreateOzonApiKey(e.target.value)}
                  placeholder="Api-Key"
                />
              </div>
            </div>
          )}
        </form>
      </section>

      <section className="panel">
        <h2 className="section-title">Список селлеров</h2>
        {loading && sellers.length === 0 && <p>Загрузка…</p>}
        {!loading && sellers.length === 0 && <p>Селлеров пока нет.</p>}
        {sellers.length > 0 && (
          <div className="sellers-table-scroll">
            <table className="sellers-table">
              <thead>
                <tr>
                  <th>Компания</th>
                  <th>Маркетплейсы / API</th>
                  <th>Аккаунт</th>
                  <th>WB: новые / сборка / доставка</th>
                  <th>Ozon: новые / сборка / доставка</th>
                  <th>Тариф</th>
                  <th>Ссылка</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {sellers.map((seller) => (
                  <tr key={seller.id}>
                    <td>
                      <strong>{seller.company_name}</strong>
                      {!seller.is_active && <span className="sellers-tag sellers-tag--muted">неактивен</span>}
                    </td>
                    <td>
                      {seller.wb_enabled && (
                        <span className="sellers-tag sellers-tag--wb">
                          WB{seller.has_wb_token ? ' ✓' : ''}
                        </span>
                      )}
                      {seller.ozon_enabled && (
                        <span className="sellers-tag sellers-tag--ozon">
                          Ozon{seller.has_ozon_api ? ' ✓' : ''}
                        </span>
                      )}
                    </td>
                    <td>
                      {seller.has_account ? (
                        <span className="sellers-tag sellers-tag--ok">{seller.username}</span>
                      ) : (
                        <span className="sellers-tag sellers-tag--warn">не зарегистрирован</span>
                      )}
                    </td>
                    <td>
                      {seller.wb_count_new} / {seller.wb_count_assembly} / {seller.wb_count_delivery}
                    </td>
                    <td>
                      {seller.ozon_count_new} / {seller.ozon_count_assembly} / {seller.ozon_count_delivery}
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn btn--ghost btn--sm"
                        onClick={() => setTariffSeller(seller)}
                      >
                        Тариф
                      </button>
                    </td>
                    <td>
                      {seller.has_account ? (
                        <span className="sellers-tag sellers-tag--muted">—</span>
                      ) : (
                        <button
                          type="button"
                          className="btn btn--ghost btn--sm"
                          onClick={() => copyInvite(seller)}
                        >
                          {copiedId === seller.id
                            ? 'Скопировано'
                            : seller.invite_token
                              ? 'Копировать ссылку'
                              : 'Новая ссылка'}
                        </button>
                      )}
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn btn--ghost btn--sm"
                        onClick={() => openEdit(seller)}
                      >
                        Изменить
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {editSeller && (
        <section className="panel sellers-create-panel sellers-edit-panel">
          <h2 className="section-title">Редактирование: {editSeller.company_name}</h2>
          <form className="sellers-form" onSubmit={handleSaveEdit}>
            <div className="sellers-form__row">
              <input
                type="text"
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                placeholder="Название компании"
                required
              />
              <label className="sellers-mp-check">
                <input
                  type="checkbox"
                  checked={editSeller.is_active}
                  onChange={(e) => setEditSeller({ ...editSeller, is_active: e.target.checked })}
                />
                Активен
              </label>
              <label className="sellers-mp-check">
                <input
                  type="checkbox"
                  checked={editWbEnabled}
                  onChange={(e) => setEditWbEnabled(e.target.checked)}
                />
                WB
              </label>
              <label className="sellers-mp-check">
                <input
                  type="checkbox"
                  checked={editOzonEnabled}
                  onChange={(e) => setEditOzonEnabled(e.target.checked)}
                />
                Ozon
              </label>
            </div>

            {editWbEnabled && (
              <div className="sellers-form__block">
                <strong>Токен WB</strong>
                <p className="sellers-ozon-hint">
                  {editSeller.has_wb_token
                    ? 'Токен уже подключён. Вставьте новый, чтобы заменить.'
                    : 'Токен не задан.'}
                </p>
                <div className="sellers-form__row">
                  <input
                    type="password"
                    value={editWbToken}
                    onChange={(e) => setEditWbToken(e.target.value)}
                    placeholder="Новый токен WB"
                  />
                  {editSeller.has_wb_token && (
                    <button
                      type="button"
                      className="btn btn--ghost"
                      disabled={savingEdit}
                      onClick={async () => {
                        if (!window.confirm('Удалить токен WB?')) return
                        setSavingEdit(true)
                        setError('')
                        try {
                          await clearSellerWbToken(editSeller.id)
                          setMessage('Токен WB удалён')
                          setEditSeller({ ...editSeller, has_wb_token: false })
                          await load()
                        } catch (err) {
                          setError(err instanceof Error ? err.message : 'Ошибка')
                        } finally {
                          setSavingEdit(false)
                        }
                      }}
                    >
                      Удалить токен
                    </button>
                  )}
                </div>
              </div>
            )}

            {editOzonEnabled && (
              <div className="sellers-form__block">
                <strong>Ключи Ozon</strong>
                <p className="sellers-ozon-hint">
                  {editSeller.has_ozon_api
                    ? `Client-Id: ${editSeller.ozon_client_id || '—'}. Введите Api-Key для замены.`
                    : 'Ключи не заданы.'}
                </p>
                <div className="sellers-form__row">
                  <input
                    type="text"
                    value={editOzonClientId}
                    onChange={(e) => setEditOzonClientId(e.target.value)}
                    placeholder="Client-Id"
                  />
                  <input
                    type="password"
                    value={editOzonApiKey}
                    onChange={(e) => setEditOzonApiKey(e.target.value)}
                    placeholder="Api-Key"
                  />
                  {editSeller.has_ozon_api && (
                    <button
                      type="button"
                      className="btn btn--ghost"
                      disabled={savingEdit}
                      onClick={async () => {
                        if (!window.confirm('Удалить ключи Ozon?')) return
                        setSavingEdit(true)
                        setError('')
                        try {
                          await clearSellerOzonKeys(editSeller.id)
                          setMessage('Ключи Ozon удалены')
                          setEditSeller({
                            ...editSeller,
                            has_ozon_api: false,
                            ozon_client_id: '',
                          })
                          setEditOzonClientId('')
                          await load()
                        } catch (err) {
                          setError(err instanceof Error ? err.message : 'Ошибка')
                        } finally {
                          setSavingEdit(false)
                        }
                      }}
                    >
                      Удалить ключи
                    </button>
                  )}
                </div>
              </div>
            )}

            <div className="sellers-form__actions">
              <button type="submit" className="btn btn--primary" disabled={savingEdit}>
                {savingEdit ? 'Сохранение…' : 'Сохранить'}
              </button>
              <button type="button" className="btn btn--ghost" onClick={() => setEditSeller(null)}>
                Отмена
              </button>
              <button
                type="button"
                className="btn btn--danger-outline"
                disabled={savingEdit}
                onClick={() => void handleDeleteSeller()}
              >
                Удалить селлера
              </button>
            </div>
          </form>
        </section>
      )}

      {tariffSeller && (
        <SellerTariffModal
          seller={tariffSeller}
          onClose={() => setTariffSeller(null)}
          onApplied={(text) => setMessage(text)}
        />
      )}
    </>
  )
}
