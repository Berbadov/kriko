import { motion } from 'motion/react'
import { useState } from 'react'
import type { Product } from '../activity/run'
import { useProductActions } from '../engine/products'
import { usePrefs } from '../prefs'
import { Icon } from './Icon'
import { PixelGlyph } from './PixelGlyph'

/** A product that an answer named, with what the reader can do next. */
export function ProductCard({ product, onOpen }: { product: Product; onOpen: (lookupId: string) => void }) {
  const { motion: m } = usePrefs()
  const { adding, reading, ensureCheck, addToCompare, readAgain } = useProductActions(product)
  const [openProblem, setOpenProblem] = useState('')
  const note = openProblem || (adding.step === 'failed' ? adding.note : reading.step === 'failed' ? reading.note : '')

  return (
    <motion.div
      className="product-card"
      initial={{ opacity: 0, y: m.d(14), scale: m.on ? 0.98 : 1 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={m.tx.spring}
    >
      <div>
        <strong>{product.name}</strong>
        <span className="mono">{reading.step === 'busy' ? reading.note : product.note}</span>
        {note && (
          <span className="error-line" role="alert">
            {note}
          </span>
        )}
      </div>
      <div className="card-actions">
        <button className="btn" onClick={() => { setOpenProblem(''); void ensureCheck().then(onOpen).catch((error: unknown) => setOpenProblem(error instanceof Error ? error.message : 'The product could not be opened. Try again.')) }}>
          Open
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
