import { useState } from 'react'
import { motion } from 'motion/react'
import { usePrefs } from '../prefs'
import type { Product } from '../activity/run'
import { useFocus } from '../chat/focus'
import { productKey } from '../chat/view'
import { Icon } from './Icon'
import { ProductCard } from './ProductCard'
import { Fold } from './text'

/** Up to this many products are drawn as cards where they are named. More than
 *  that is a list the reader opens: the thread is for the answer, and a long run
 *  of cards pushes it off the screen. */
const SHOWN = 2

/** The products one answer named. Sources never appear here: the pages a turn
 *  read live in the column beside the thread, and this is only what was named. */
export function ProductList({ products, onOpen }: { products: Product[]; onOpen: (lookupId: string) => void }) {
  const focus = useFocus()
  const { motion: m } = usePrefs()
  // The grid arrives as one motion: each card rises a beat after the one before it.
  const grid = { hidden: {}, show: { transition: { staggerChildren: 0.07 } } }
  const card = { hidden: { opacity: 0, y: m.d(10) }, show: { opacity: 1, y: 0, transition: m.tx.soft } }
  const cards = (list: Product[]) => (
    <motion.div variants={grid} initial="hidden" animate="show">
      {list.map((product) => (
        <motion.div key={product.id} variants={card}>
          <ProductCard product={product} onOpen={onOpen} />
        </motion.div>
      ))}
    </motion.div>
  )
  /** The reader's own press. Until they make one, the list is open only for a product picked in the column. */
  const [chosen, setChosen] = useState<boolean | null>(null)
  const lit = products.some((product) => focus.key === productKey(product.id))
  const open = chosen ?? lit
  if (!products.length) return null
  if (products.length <= SHOWN) return <>{cards(products)}</>
  const names = products.slice(0, 3).map((product) => product.name).join(' · ')
  return (
    <section className="product-list" aria-label="Products named in the answer">
      <button className="pl-head" onClick={() => setChosen(!open)} aria-expanded={open}>
        <Icon name="queue" size={15} />
        <span className="pl-title">{products.length} products</span>
        <span className="pl-names">{names}</span>
        <span className="tl-chev" data-open={open}>
          <Icon name="chevron" size={16} />
        </span>
      </button>
      <Fold open={open}>
        <div className="pl-body">{cards(products)}</div>
      </Fold>
    </section>
  )
}
