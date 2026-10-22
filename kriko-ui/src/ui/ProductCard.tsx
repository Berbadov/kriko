import { useState } from 'react'
import { motion } from 'motion/react'
import type { Product } from '../activity/run'
import { useFocus } from '../chat/focus'
import { productKey } from '../chat/view'
import { useProductActions } from '../engine/products'
import { usePrefs } from '../prefs'
import { ExternalLink } from './ExternalLink'
import { Icon } from './Icon'
import { PixelGlyph } from './PixelGlyph'

/** A product that an answer named, with what the reader can do next. */
export function ProductCard({ product, onOpen }: { product: Product; onOpen: (lookupId: string) => void }) {
  if (product.kind === 'listing') return <ListingCard product={product} />
  return <CatalogProductCard product={product} onOpen={onOpen} />
}

function CatalogProductCard({ product, onOpen }: { product: Product; onOpen: (lookupId: string) => void }) {
  const { motion: m } = usePrefs()
  const { adding, reading, opening, open, addToCompare, readAgain } = useProductActions(product)
  const focus = useFocus()
  const key = productKey(product.id)
  const note = adding.step === 'failed' ? adding.note
    : reading.step === 'failed' ? reading.note
      : opening.step === 'failed' ? opening.note
        : ''

  return (
    <motion.div
      className="product-card"
      data-focus-key={key}
      data-lit={focus.key === key || undefined}
      onClick={() => focus.select(key, 'thread')}
      initial={{ opacity: 0, y: m.d(14), scale: m.on ? 0.98 : 1 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={m.tx.spring}
    >
      <div>
        <strong>{product.name}</strong>
        <span className="mono">{reading.step === 'busy' ? reading.note : opening.step === 'busy' ? opening.note : product.note}</span>
        {note && (
          <span className="error-line" role="alert">
            {note}
          </span>
        )}
      </div>
      <div className="card-actions">
        <button className="btn" onClick={() => void open(onOpen)} disabled={opening.step === 'busy'}>
          {opening.step === 'busy' ? <PixelGlyph size={14} active /> : null}
          {opening.step === 'busy' ? 'Opens' : 'Open'}
        </button>
        <button className="btn" onClick={() => void addToCompare()} disabled={adding.step === 'busy' || adding.step === 'done'}>
          {adding.step === 'done' ? <Icon name="check" size={14} /> : adding.step === 'busy' ? <PixelGlyph size={14} active /> : <Icon name="plus" size={14} />}
          {adding.step === 'done' ? 'On the board' : 'Add to Compare'}
        </button>
        <button className="btn ghost" onClick={() => void readAgain()} disabled={reading.step === 'busy'}>
          {reading.step === 'busy' ? <PixelGlyph size={14} active /> : null}
          {reading.step === 'done' ? 'Read again' : reading.step === 'busy' ? 'Reads' : 'Read again'}
        </button>
      </div>
    </motion.div>
  )
}

function ListingCard({ product }: { product: Product }) {
  const { motion: m } = usePrefs()
  const [imageFailed, setImageFailed] = useState(false)
  return (
    <motion.div
      className="product-card listing-product-card"
      initial={{ opacity: 0, y: m.d(14), scale: m.on ? 0.98 : 1 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={m.tx.spring}
    >
      <div className="listing-image" aria-hidden="true">
        {product.imageUrl && !imageFailed
          ? <img src={product.imageUrl} alt="" loading="lazy" referrerPolicy="no-referrer" onError={() => setImageFailed(true)} />
          : <Icon name="spark" size={20} />}
      </div>
      <div className="listing-info">
        <strong>{product.name}</strong>
        <span>{product.seller || 'Seller not identified'}</span>
        <span className="listing-meta">{product.trust || product.note}</span>
      </div>
      {product.url && <div className="card-actions">
        <ExternalLink className="btn" href={product.url}>View listing</ExternalLink>
      </div>}
    </motion.div>
  )
}
