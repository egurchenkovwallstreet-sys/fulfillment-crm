import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  fetchSellerIntakeReceiptDetail,
  fetchSellerIntakeReceipts,
  type SellerIntakeReceiptBrief,
  type SellerIntakeReceiptDetail,
} from '../api/sellerCabinet'
import { ProductPhotoThumb } from '../components/ProductPhotoThumb'
import { useMarketplace } from '../context/MarketplaceContext'
import { uiHint } from '../utils/uiHint'
import './SellerIntakesPage.css'

function formatReceiptDate(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString('ru-RU', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function SellerIntakesPage() {
  const { marketplace } = useMarketplace()
  const [receipts, setReceipts] = useState<SellerIntakeReceiptBrief[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<SellerIntakeReceiptDetail | null>(null)
  const [loadingList, setLoadingList] = useState(true)
  const [loadingDetail, setLoadingDetail] = useState(false)
  const [error, setError] = useState('')

  const loadList = useCallback(async () => {
    setLoadingList(true)
    setError('')
    try {
      const result = await fetchSellerIntakeReceipts(marketplace)
      setReceipts(result.receipts)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось загрузить приёмки')
    } finally {
      setLoadingList(false)
    }
  }, [marketplace])

  useEffect(() => {
    void loadList()
  }, [loadList])

  useEffect(() => {
    if (receipts.length === 0) {
      setSelectedId(null)
      return
    }
    setSelectedId((current) =>
      current && receipts.some((r) => r.id === current) ? current : receipts[0].id,
    )
  }, [receipts])

  useEffect(() => {
    if (!selectedId) {
      setDetail(null)
      return
    }
    let cancelled = false
    setLoadingDetail(true)
    fetchSellerIntakeReceiptDetail(selectedId, marketplace)
      .then((data) => {
        if (!cancelled) setDetail(data)
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Не удалось открыть приёмку')
          setDetail(null)
        }
      })
      .finally(() => {
        if (!cancelled) setLoadingDetail(false)
      })
    return () => {
      cancelled = true
    }
  }, [selectedId, marketplace])

  return (
    <>
      <header className="topbar">
        <div>
          <h1>Приёмки</h1>
          <p>История принятого на склад товара</p>
        </div>
        <Link to="/cabinet" className="btn btn--ghost" {...uiHint('Вернуться в кабинет селлера.')}>
          ← Кабинет
        </Link>
      </header>

      {error && <div className="dashboard-sync-msg dashboard-sync-msg--error">{error}</div>}

      <div className="seller-intakes-layout">
        <section className="panel seller-intakes-list">
          <h2 className="section-title">Список</h2>
          {loadingList ? (
            <p className="seller-intakes-empty">Загрузка…</p>
          ) : receipts.length === 0 ? (
            <p className="seller-intakes-empty">Приёмок пока нет</p>
          ) : (
            <ul className="seller-intakes-list__items">
              {receipts.map((receipt) => (
                <li key={receipt.id}>
                  <button
                    type="button"
                    className={
                      selectedId === receipt.id
                        ? 'seller-intakes-list__btn seller-intakes-list__btn--active'
                        : 'seller-intakes-list__btn'
                    }
                    onClick={() => setSelectedId(receipt.id)}
                  >
                    {formatReceiptDate(receipt.created_at)}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="panel seller-intakes-detail">
          <h2 className="section-title">Состав</h2>
          {!selectedId ? (
            <p className="seller-intakes-empty">Выберите приёмку слева</p>
          ) : loadingDetail ? (
            <p className="seller-intakes-empty">Загрузка…</p>
          ) : !detail || detail.items.length === 0 ? (
            <p className="seller-intakes-empty">Нет позиций</p>
          ) : (
            <div className="seller-intakes-table-scroll">
              <table className="seller-intakes-table">
                <thead>
                  <tr>
                    <th>Фото</th>
                    <th>Баркод</th>
                    <th>Размер</th>
                    <th>Название</th>
                    <th>Принято, шт.</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.items.map((item, index) => (
                    <tr key={`${item.barcode}-${index}`}>
                      <td>
                        <ProductPhotoThumb
                          url={item.photo_url ?? ''}
                          alt={item.product_name || item.barcode}
                        />
                      </td>
                      <td>
                        <code>{item.barcode}</code>
                      </td>
                      <td>{item.tech_size || '—'}</td>
                      <td>{item.product_name || '—'}</td>
                      <td>
                        <strong>{item.quantity}</strong>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </>
  )
}
