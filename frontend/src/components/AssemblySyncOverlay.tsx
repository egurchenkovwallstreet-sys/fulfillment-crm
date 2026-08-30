import { useMarketplace } from '../context/MarketplaceContext'
import './AssemblySyncOverlay.css'

type AssemblySyncOverlayProps = {
  visible: boolean
  marketplace?: 'wb' | 'ozon'
}

export function AssemblySyncOverlay({ visible, marketplace: marketplaceProp }: AssemblySyncOverlayProps) {
  const { marketplace: ctxMarketplace } = useMarketplace()
  const marketplace = marketplaceProp ?? ctxMarketplace
  if (!visible) return null

  const label = marketplace === 'ozon' ? 'OZON' : 'WB'
  const toneClass = marketplace === 'ozon' ? 'assembly-sync-overlay--ozon' : 'assembly-sync-overlay--wb'

  return (
    <div className={`assembly-sync-overlay ${toneClass}`} role="status" aria-live="polite">
      <div className="assembly-sync-overlay__card">
        <div className="assembly-sync-overlay__scene" aria-hidden="true">
          <div className="assembly-sync-overlay__computer">
            <span className="assembly-sync-overlay__screen" />
            <span className="assembly-sync-overlay__keyboard" />
          </div>
          <div className="assembly-sync-overlay__link">
            <span className="assembly-sync-overlay__pulse assembly-sync-overlay__pulse--1" />
            <span className="assembly-sync-overlay__pulse assembly-sync-overlay__pulse--2" />
            <span className="assembly-sync-overlay__pulse assembly-sync-overlay__pulse--3" />
          </div>
          <div className="assembly-sync-overlay__satellite">
            <span className="assembly-sync-overlay__dish" />
            <span className="assembly-sync-overlay__body" />
          </div>
        </div>
        <div className={`assembly-sync-overlay__badge assembly-sync-overlay__badge--${marketplace}`}>
          {label}
        </div>
        <p className="assembly-sync-overlay__text">
          Подождите немного, мы качаем актуальные данные
        </p>
      </div>
    </div>
  )
}
