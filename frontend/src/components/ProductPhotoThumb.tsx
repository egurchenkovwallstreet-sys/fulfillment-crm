import { useState } from 'react'
import './ProductPhotoThumb.css'

type Props = {
  url: string
  alt: string
}

export function ProductPhotoThumb({ url, alt }: Props) {
  const [zoomed, setZoomed] = useState(false)

  if (!url) {
    return <span className="product-photo product-photo--empty">—</span>
  }

  function toggleZoom() {
    setZoomed((value) => !value)
  }

  return (
    <>
      <button
        type="button"
        className="product-photo-btn"
        onClick={toggleZoom}
        aria-label={zoomed ? 'Уменьшить фото' : 'Увеличить фото'}
        aria-pressed={zoomed}
      >
        <img src={url} alt={alt} className="product-photo" />
      </button>
      {zoomed && (
        <div
          className="product-photo-zoom-backdrop"
          role="presentation"
          onClick={toggleZoom}
        >
          <img
            src={url}
            alt={alt}
            className="product-photo-zoom"
            onClick={(e) => {
              e.stopPropagation()
              toggleZoom()
            }}
          />
        </div>
      )}
    </>
  )
}
