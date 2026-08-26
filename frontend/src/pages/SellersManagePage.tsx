import { useCallback, useEffect, useState, type FormEvent } from 'react'
import {
  createSeller,
  fetchSellerInvite,
  fetchSellersManage,
  saveSellerOzonKeys,
  updateSellerMarketplaces,
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
  const [creating, setCreating] = useState(false)
  const [copiedId, setCopiedId] = useState<number | null>(null)
  const [message, setMessage] = useState('')
  const [tariffSeller, setTariffSeller] = useState<SellerManageItem | null>(null)
  const [ozonSellerId, setOzonSellerId] = useState<number | null>(null)
  const [ozonClientId, setOzonClientId] = useState('')
  const [ozonApiKey, setOzonApiKey] = useState('')
  const [savingOzon, setSavingOzon] = useState(false)

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
      })
      setCompanyName('')
      setMessage(`Селлер «${created.company_name}» создан. Скопируйте ссылку для регистрации.`)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка создания')
    } finally {
      setCreating(false)
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
          <p>Создание селлеров, тарифы и одноразовые ссылки для регистрации</p>
        </div>
        <button type="button" className="btn btn--ghost" onClick={load} disabled={loading}>
          Обновить
        </button>
      </header>

      {error && <div className="dashboard-sync-msg dashboard-sync-msg--error">{error}</div>}
      {message && <div className="dashboard-sync-msg dashboard-sync-msg--ok">{message}</div>}

      <section className="panel sellers-create-panel">
        <h2 className="section-title">Новый селлер</h2>
        <form className="sellers-create-form" onSubmit={handleCreate}>
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
                  <th>Маркетплейсы</th>
                  <th>Аккаунт</th>
                  <th>WB: новые / сборка / доставка</th>
                  <th>Ozon: новые / сборка / доставка</th>
                  <th>Тариф</th>
                  <th>Ссылка</th>
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
                      {seller.wb_enabled && <span className="sellers-tag sellers-tag--wb">WB</span>}
                      {seller.ozon_enabled && <span className="sellers-tag sellers-tag--ozon">Ozon</span>}
                      {!seller.wb_enabled && (
                        <button
                          type="button"
                          className="btn btn--ghost btn--sm"
                          onClick={() =>
                            updateSellerMarketplaces(seller.id, { wb_enabled: true }).then(load)
                          }
                        >
                          + WB
                        </button>
                      )}
                      {!seller.ozon_enabled && (
                        <button
                          type="button"
                          className="btn btn--ghost btn--sm"
                          onClick={() => {
                            setOzonSellerId(seller.id)
                            setOzonClientId(seller.ozon_client_id || '')
                            setOzonApiKey('')
                          }}
                        >
                          + Ozon
                        </button>
                      )}
                      {seller.ozon_enabled && (
                        <button
                          type="button"
                          className="btn btn--ghost btn--sm"
                          onClick={() => {
                            setOzonSellerId(seller.id)
                            setOzonClientId(seller.ozon_client_id || '')
                            setOzonApiKey('')
                          }}
                        >
                          {seller.has_ozon_api ? 'Ключи Ozon' : 'Ключи Ozon'}
                        </button>
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
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {ozonSellerId !== null && (
        <section className="panel sellers-create-panel">
          <h2 className="section-title">Ключи Ozon Seller API</h2>
          <p className="sellers-ozon-hint">
            ЛК seller.ozon.ru → Настройки → API-ключи: скопируйте Client-Id и Api-Key.
          </p>
          <form
            className="sellers-create-form"
            onSubmit={async (e) => {
              e.preventDefault()
              setSavingOzon(true)
              setError('')
              setMessage('')
              try {
                const result = await saveSellerOzonKeys(ozonSellerId, {
                  client_id: ozonClientId.trim(),
                  api_key: ozonApiKey.trim(),
                })
                setMessage(result.detail)
                setOzonSellerId(null)
                setOzonApiKey('')
                await load()
              } catch (err) {
                setError(err instanceof Error ? err.message : 'Не удалось сохранить ключи Ozon')
              } finally {
                setSavingOzon(false)
              }
            }}
          >
            <input
              type="text"
              value={ozonClientId}
              onChange={(e) => setOzonClientId(e.target.value)}
              placeholder="Client-Id"
              required
            />
            <input
              type="password"
              value={ozonApiKey}
              onChange={(e) => setOzonApiKey(e.target.value)}
              placeholder="Api-Key"
              required
            />
            <button type="submit" className="btn btn--primary" disabled={savingOzon}>
              {savingOzon ? 'Проверка…' : 'Сохранить и проверить'}
            </button>
            <button type="button" className="btn btn--ghost" onClick={() => setOzonSellerId(null)}>
              Отмена
            </button>
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
